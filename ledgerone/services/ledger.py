from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import utcnow
from ledgerone.models.ledger import Account, AccountingPeriod, Journal, JournalLine
from ledgerone.services.context import AccessContext


class LedgerError(ValueError):
    pass


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise LedgerError(f"Invalid monetary value: {value}") from exc


class LedgerService:
    """Single posting service used by UI, APIs, business modules and local AI."""

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
    def post_journal(context: AccessContext, *, journal_date: date, description: str,
                     lines: list[dict], reference: str | None = None,
                     source_module: str = "ledger", source_reference: str | None = None,
                     metadata: dict | None = None, commit: bool = True,
                     enforce_permission: bool = True):
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
        if len(lines) < 2:
            raise LedgerError("A journal requires at least two lines")

        prepared = []
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")

        for index, raw in enumerate(lines, start=1):
            account = db.session.get(Account, raw.get("account_id"))
            if not account or account.organisation_id != context.organisation_id:
                raise LedgerError(f"Invalid account on line {index}")
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

        if total_debit != total_credit:
            raise LedgerError(
                f"Journal is not balanced: debits {total_debit} != credits {total_credit}"
            )
        if total_debit == 0:
            raise LedgerError("Journal total must be greater than zero")

        journal = Journal(
            organisation_id=context.organisation_id,
            journal_date=journal_date,
            reference=reference,
            description=description.strip(),
            source_module=source_module,
            source_reference=source_reference,
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
            metadata={"reversal_of": original.id},
            commit=False,
            enforce_permission=False,
        )
        reversal.reversal_of_id = original.id
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
