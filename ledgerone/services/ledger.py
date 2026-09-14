from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import utcnow
from ledgerone.models.ledger import (
    Account,
    AccountingPeriod,
    Journal,
    JournalLine,
    OpeningBalanceBatch,
    RecurringJournal,
    RecurringJournalRun,
)
from ledgerone.services.context import AccessContext


class LedgerError(ValueError):
    pass


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise LedgerError(f"Invalid monetary value: {value}") from exc


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _advance_frequency(value: date, frequency: str) -> date:
    if frequency == "weekly":
        return value + timedelta(days=7)
    if frequency == "monthly":
        return _add_months(value, 1)
    if frequency == "quarterly":
        return _add_months(value, 3)
    if frequency == "annual":
        return _add_months(value, 12)
    raise LedgerError(f"Unsupported recurring frequency: {frequency}")


class LedgerService:
    """Single posting service used by UI, APIs, business modules and local AI."""

    RECURRING_FREQUENCIES = ("weekly", "monthly", "quarterly", "annual")

    @staticmethod
    def _audit(context: AccessContext, *, action: str, entity_type: str,
               entity_id: str | None, detail: dict | None = None):
        db.session.add(
            AuditEvent(
                organisation_id=context.organisation_id,
                actor_type=context.identity_type,
                actor_id=context.user_id or context.api_key_id,
                module_id="ledger",
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                detail=detail or {},
            )
        )

    @staticmethod
    def list_accounts(context: AccessContext):
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        return Account.query.filter_by(
            organisation_id=context.organisation_id
        ).order_by(Account.code.asc()).all()

    @staticmethod
    def create_account(context: AccessContext, *, code: str, name: str, account_type: str,
                       currency: str | None = None, parent_id: str | None = None):
        if not context.can("ledger.accounts.write"):
            raise PermissionError("ledger.accounts.write")
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise LedgerError("Account code and name are required")
        if Account.query.filter_by(organisation_id=context.organisation_id, code=code).first():
            raise LedgerError(f"Account code {code} already exists")
        account = Account(
            organisation_id=context.organisation_id,
            code=code,
            name=name,
            account_type=account_type.strip().lower(),
            currency=currency.upper() if currency else None,
            parent_id=parent_id,
        )
        db.session.add(account)
        LedgerService._audit(
            context,
            action="account_created",
            entity_type="account",
            entity_id=account.id,
            detail={"code": account.code, "name": account.name, "account_type": account.account_type},
        )
        db.session.commit()
        return account

    @staticmethod
    def list_periods(context: AccessContext):
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        return (
            AccountingPeriod.query.filter_by(organisation_id=context.organisation_id)
            .order_by(AccountingPeriod.start_date.desc())
            .all()
        )

    @staticmethod
    def create_period(context: AccessContext, *, name: str, start_date: date, end_date: date):
        if not context.can("ledger.periods.manage"):
            raise PermissionError("ledger.periods.manage")
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        name = (name or "").strip()
        if not name:
            raise LedgerError("Period name is required")
        if end_date < start_date:
            raise LedgerError("Period end date cannot be before its start date")
        overlap = AccountingPeriod.query.filter(
            AccountingPeriod.organisation_id == context.organisation_id,
            AccountingPeriod.start_date <= end_date,
            AccountingPeriod.end_date >= start_date,
        ).first()
        if overlap:
            raise LedgerError(f"Period overlaps {overlap.name}")
        period = AccountingPeriod(
            organisation_id=context.organisation_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            status="open",
        )
        db.session.add(period)
        db.session.flush()
        LedgerService._audit(
            context,
            action="period_created",
            entity_type="accounting_period",
            entity_id=period.id,
            detail={"name": period.name, "start_date": str(start_date), "end_date": str(end_date)},
        )
        db.session.commit()
        return period

    @staticmethod
    def set_period_locked(context: AccessContext, period_id: str, *, locked: bool):
        if not context.can("ledger.periods.manage"):
            raise PermissionError("ledger.periods.manage")
        period = db.session.get(AccountingPeriod, period_id)
        if not period or period.organisation_id != context.organisation_id:
            raise LedgerError("Accounting period not found")
        period.status = "locked" if locked else "open"
        period.locked_at = utcnow() if locked else None
        period.locked_by_user_id = context.user_id if locked else None
        LedgerService._audit(
            context,
            action="period_locked" if locked else "period_unlocked",
            entity_type="accounting_period",
            entity_id=period.id,
            detail={"name": period.name, "status": period.status},
        )
        db.session.commit()
        return period

    @staticmethod
    def assert_posting_date_open(context: AccessContext, posting_date: date):
        locked_period = AccountingPeriod.query.filter(
            AccountingPeriod.organisation_id == context.organisation_id,
            AccountingPeriod.start_date <= posting_date,
            AccountingPeriod.end_date >= posting_date,
            AccountingPeriod.status == "locked",
        ).first()
        if locked_period:
            raise LedgerError(
                f"Posting date {posting_date.isoformat()} is in locked period {locked_period.name}"
            )

    @staticmethod
    def _prepare_lines(context: AccessContext, lines: list[dict], *, minimum_lines: int = 2,
                       require_balanced: bool = True):
        if len(lines) < minimum_lines:
            raise LedgerError(
                "A journal requires at least two lines" if minimum_lines == 2
                else "At least one opening balance is required"
            )

        prepared = []
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")

        for index, raw in enumerate(lines, start=1):
            account = db.session.get(Account, raw.get("account_id"))
            if not account or account.organisation_id != context.organisation_id:
                raise LedgerError(f"Invalid account on line {index}")
            if not account.is_active:
                raise LedgerError(f"Account {account.code} is inactive")
            debit = _money(raw.get("debit"))
            credit = _money(raw.get("credit"))
            if debit < 0 or credit < 0:
                raise LedgerError("Debit and credit values cannot be negative")
            if debit and credit:
                raise LedgerError(f"Line {index} cannot contain both a debit and a credit")
            if not debit and not credit:
                raise LedgerError(f"Line {index} must contain a debit or a credit")
            total_debit += debit
            total_credit += credit
            prepared.append((index, account, debit, credit, raw))

        if require_balanced and total_debit != total_credit:
            raise LedgerError(
                f"Journal is not balanced: debits {total_debit} != credits {total_credit}"
            )
        if require_balanced and total_debit == 0:
            raise LedgerError("Journal total must be greater than zero")
        return prepared, total_debit, total_credit

    @staticmethod
    def post_journal(context: AccessContext, *, journal_date: date, description: str,
                     lines: list[dict], reference: str | None = None,
                     source_module: str = "ledger", source_reference: str | None = None,
                     metadata: dict | None = None, commit: bool = True,
                     enforce_permission: bool = True, reversal_of_id: str | None = None):
        if enforce_permission:
            can_post_directly = context.can("ledger.journals.post")
            can_post_for_module = (
                source_module not in {"ledger", "api"}
                and context.can(f"{source_module}.write")
            )
            if not (can_post_directly or can_post_for_module):
                raise PermissionError("ledger.journals.post")
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        LedgerService.assert_posting_date_open(context, journal_date)
        prepared, total_debit, total_credit = LedgerService._prepare_lines(context, lines)

        journal = Journal(
            organisation_id=context.organisation_id,
            journal_date=journal_date,
            reference=reference,
            description=description.strip() or "Journal",
            source_module=source_module,
            source_reference=source_reference,
            reversal_of_id=reversal_of_id,
            created_by_user_id=context.user_id,
            posted_at=utcnow(),
            metadata_json=metadata or {},
        )
        db.session.add(journal)
        db.session.flush()

        for index, account, debit, credit, raw in prepared:
            db.session.add(
                JournalLine(
                    journal_id=journal.id,
                    account_id=account.id,
                    line_number=index,
                    description=raw.get("description"),
                    debit=debit,
                    credit=credit,
                    currency=raw.get("currency"),
                    foreign_amount=_money(raw["foreign_amount"]) if raw.get("foreign_amount") is not None else None,
                    dimensions=raw.get("dimensions") or {},
                )
            )

        LedgerService._audit(
            context,
            action="journal_posted",
            entity_type="journal",
            entity_id=journal.id,
            detail={
                "date": journal_date.isoformat(),
                "reference": reference,
                "source_module": source_module,
                "total_debit": str(total_debit),
                "total_credit": str(total_credit),
                "reversal_of_id": reversal_of_id,
            },
        )
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return journal

    @staticmethod
    def reverse_journal(context: AccessContext, journal_id: str, *, reversal_date: date,
                        reason: str | None = None):
        if not context.can("ledger.journals.reverse"):
            raise PermissionError("ledger.journals.reverse")
        original = db.session.get(Journal, journal_id)
        if not original or original.organisation_id != context.organisation_id:
            raise LedgerError("Journal not found")
        if original.status != "posted":
            raise LedgerError("Only posted journals can be reversed")
        if original.reversal_of_id:
            raise LedgerError("A reversal journal cannot itself be reversed")
        existing = Journal.query.filter_by(
            organisation_id=context.organisation_id,
            reversal_of_id=original.id,
            status="posted",
        ).first()
        if existing:
            raise LedgerError("Journal has already been reversed")

        lines = []
        for line in original.lines:
            dimensions = dict(line.dimensions or {})
            dimensions["reversal_of_line_id"] = line.id
            foreign_amount = -line.foreign_amount if line.foreign_amount is not None else None
            lines.append(
                {
                    "account_id": line.account_id,
                    "description": line.description,
                    "debit": line.credit,
                    "credit": line.debit,
                    "currency": line.currency,
                    "foreign_amount": foreign_amount,
                    "dimensions": dimensions,
                }
            )

        reversal = LedgerService.post_journal(
            context,
            journal_date=reversal_date,
            description=(reason or "").strip() or f"Reversal: {original.description}",
            reference=f"REV-{original.reference or original.id[:8]}",
            lines=lines,
            source_module="ledger",
            source_reference=original.id,
            reversal_of_id=original.id,
            metadata={"reversal_of": original.id},
            commit=False,
            enforce_permission=False,
        )
        LedgerService._audit(
            context,
            action="journal_reversed",
            entity_type="journal",
            entity_id=reversal.id,
            detail={"reversal_of": original.id, "reversal_date": str(reversal_date)},
        )
        db.session.commit()
        return reversal

    @staticmethod
    def list_opening_balance_batches(context: AccessContext):
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        return (
            OpeningBalanceBatch.query.filter_by(organisation_id=context.organisation_id)
            .order_by(OpeningBalanceBatch.as_of_date.desc(), OpeningBalanceBatch.created_at.desc())
            .all()
        )

    @staticmethod
    def create_opening_balance_batch(context: AccessContext, *, as_of_date: date,
                                     entries: list[dict], balancing_account_id: str | None = None,
                                     reference: str | None = None,
                                     description: str = "Opening balances"):
        if not context.can("ledger.opening_balances.manage"):
            raise PermissionError("ledger.opening_balances.manage")
        if not context.organisation_id:
            raise LedgerError("An organisation is required")

        clean_entries = []
        for raw in entries:
            debit = _money(raw.get("debit"))
            credit = _money(raw.get("credit"))
            if not debit and not credit:
                continue
            clean_entries.append({**raw, "debit": debit, "credit": credit})

        prepared, total_debit, total_credit = LedgerService._prepare_lines(
            context,
            clean_entries,
            minimum_lines=1,
            require_balanced=False,
        )
        final_lines = [
            {
                "account_id": account.id,
                "description": raw.get("description") or "Opening balance",
                "debit": debit,
                "credit": credit,
                "currency": raw.get("currency"),
                "foreign_amount": raw.get("foreign_amount"),
                "dimensions": {**(raw.get("dimensions") or {}), "opening_balance": True},
            }
            for _, account, debit, credit, raw in prepared
        ]

        if total_debit != total_credit:
            balancing_account = db.session.get(Account, balancing_account_id) if balancing_account_id else None
            if not balancing_account or balancing_account.organisation_id != context.organisation_id:
                raise LedgerError("A valid balancing account is required for unbalanced opening entries")
            if balancing_account.account_type != "equity":
                raise LedgerError("The opening-balance balancing account must be an equity account")
            difference = total_debit - total_credit
            final_lines.append(
                {
                    "account_id": balancing_account.id,
                    "description": "Opening balance offset",
                    "debit": abs(difference) if difference < 0 else Decimal("0.00"),
                    "credit": difference if difference > 0 else Decimal("0.00"),
                    "dimensions": {"opening_balance": True, "balancing_line": True},
                }
            )
        elif len(final_lines) < 2:
            raise LedgerError("Balanced opening balances require at least two entered accounts")

        journal = LedgerService.post_journal(
            context,
            journal_date=as_of_date,
            description=(description or "Opening balances").strip() or "Opening balances",
            reference=(reference or "").strip() or f"OPEN-{as_of_date.isoformat()}",
            lines=final_lines,
            source_module="ledger",
            source_reference="opening_balances",
            metadata={"opening_balance": True},
            commit=False,
            enforce_permission=False,
        )
        batch = OpeningBalanceBatch(
            organisation_id=context.organisation_id,
            as_of_date=as_of_date,
            reference=journal.reference,
            description=journal.description,
            balancing_account_id=balancing_account_id or None,
            journal_id=journal.id,
            created_by_user_id=context.user_id,
        )
        db.session.add(batch)
        db.session.flush()
        LedgerService._audit(
            context,
            action="opening_balances_posted",
            entity_type="opening_balance_batch",
            entity_id=batch.id,
            detail={"journal_id": journal.id, "as_of_date": as_of_date.isoformat()},
        )
        db.session.commit()
        return batch

    @staticmethod
    def list_recurring_journals(context: AccessContext):
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        return (
            RecurringJournal.query.filter_by(organisation_id=context.organisation_id)
            .order_by(RecurringJournal.is_active.desc(), RecurringJournal.next_run_date.asc())
            .all()
        )

    @staticmethod
    def create_recurring_journal(context: AccessContext, *, name: str, description: str,
                                 frequency: str, next_run_date: date, lines: list[dict],
                                 reference: str | None = None, end_date: date | None = None):
        if not context.can("ledger.recurring.manage"):
            raise PermissionError("ledger.recurring.manage")
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        name = (name or "").strip()
        description = (description or "").strip()
        frequency = (frequency or "").strip().lower()
        if not name or not description:
            raise LedgerError("Recurring journal name and description are required")
        if frequency not in LedgerService.RECURRING_FREQUENCIES:
            raise LedgerError("Frequency must be weekly, monthly, quarterly or annual")
        if end_date and end_date < next_run_date:
            raise LedgerError("End date cannot be before the first run date")

        prepared, _, _ = LedgerService._prepare_lines(context, lines)
        template_lines = [
            {
                "account_id": account.id,
                "description": raw.get("description"),
                "debit": str(debit),
                "credit": str(credit),
                "currency": raw.get("currency"),
                "foreign_amount": str(_money(raw["foreign_amount"])) if raw.get("foreign_amount") is not None else None,
                "dimensions": raw.get("dimensions") or {},
            }
            for _, account, debit, credit, raw in prepared
        ]
        row = RecurringJournal(
            organisation_id=context.organisation_id,
            name=name,
            description=description,
            reference=(reference or "").strip() or None,
            frequency=frequency,
            next_run_date=next_run_date,
            end_date=end_date,
            is_active=True,
            template_lines=template_lines,
            created_by_user_id=context.user_id,
        )
        db.session.add(row)
        db.session.flush()
        LedgerService._audit(
            context,
            action="recurring_journal_created",
            entity_type="recurring_journal",
            entity_id=row.id,
            detail={"frequency": frequency, "next_run_date": next_run_date.isoformat()},
        )
        db.session.commit()
        return row

    @staticmethod
    def set_recurring_journal_active(context: AccessContext, recurring_id: str, *, active: bool):
        if not context.can("ledger.recurring.manage"):
            raise PermissionError("ledger.recurring.manage")
        row = db.session.get(RecurringJournal, recurring_id)
        if not row or row.organisation_id != context.organisation_id:
            raise LedgerError("Recurring journal not found")
        if active and row.end_date and row.next_run_date > row.end_date:
            raise LedgerError("Recurring journal has passed its end date")
        row.is_active = bool(active)
        LedgerService._audit(
            context,
            action="recurring_journal_enabled" if active else "recurring_journal_disabled",
            entity_type="recurring_journal",
            entity_id=row.id,
            detail={"next_run_date": row.next_run_date.isoformat()},
        )
        db.session.commit()
        return row

    @staticmethod
    def run_recurring_journal(context: AccessContext, recurring_id: str):
        if not context.can("ledger.recurring.manage"):
            raise PermissionError("ledger.recurring.manage")
        row = db.session.get(RecurringJournal, recurring_id)
        if not row or row.organisation_id != context.organisation_id:
            raise LedgerError("Recurring journal not found")
        if not row.is_active:
            raise LedgerError("Recurring journal is inactive")

        scheduled_date = row.next_run_date
        if row.end_date and scheduled_date > row.end_date:
            row.is_active = False
            db.session.commit()
            raise LedgerError("Recurring journal has reached its end date")
        existing = RecurringJournalRun.query.filter_by(
            recurring_journal_id=row.id,
            scheduled_date=scheduled_date,
        ).first()
        if existing:
            raise LedgerError("This scheduled recurring journal has already been posted")

        reference_base = row.reference or "REC"
        journal = LedgerService.post_journal(
            context,
            journal_date=scheduled_date,
            description=row.description,
            reference=f"{reference_base}-{scheduled_date.strftime('%Y%m%d')}"[:120],
            lines=list(row.template_lines or []),
            source_module="ledger",
            source_reference=f"recurring:{row.id}",
            metadata={"recurring_journal_id": row.id, "scheduled_date": scheduled_date.isoformat()},
            commit=False,
            enforce_permission=False,
        )
        run = RecurringJournalRun(
            recurring_journal_id=row.id,
            scheduled_date=scheduled_date,
            journal_id=journal.id,
        )
        db.session.add(run)
        row.last_run_date = scheduled_date
        row.run_count = int(row.run_count or 0) + 1
        row.next_run_date = _advance_frequency(scheduled_date, row.frequency)
        if row.end_date and row.next_run_date > row.end_date:
            row.is_active = False
        LedgerService._audit(
            context,
            action="recurring_journal_posted",
            entity_type="recurring_journal",
            entity_id=row.id,
            detail={
                "journal_id": journal.id,
                "scheduled_date": scheduled_date.isoformat(),
                "next_run_date": row.next_run_date.isoformat(),
            },
        )
        db.session.commit()
        return journal, run, row

    @staticmethod
    def trial_balance(context: AccessContext):
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
        rows = (
            db.session.query(
                Account.id,
                Account.code,
                Account.name,
                Account.account_type,
                db.func.coalesce(db.func.sum(JournalLine.debit), 0).label("debit"),
                db.func.coalesce(db.func.sum(JournalLine.credit), 0).label("credit"),
            )
            .outerjoin(JournalLine, JournalLine.account_id == Account.id)
            .outerjoin(Journal, Journal.id == JournalLine.journal_id)
            .filter(Account.organisation_id == context.organisation_id)
            .filter(db.or_(Journal.id.is_(None), Journal.status == "posted"))
            .group_by(Account.id, Account.code, Account.name, Account.account_type)
            .order_by(Account.code.asc())
            .all()
        )
        return [
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "account_type": row.account_type,
                "debit": _money(row.debit),
                "credit": _money(row.credit),
                "balance": _money(row.debit) - _money(row.credit),
            }
            for row in rows
        ]
