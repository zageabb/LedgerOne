from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.models.core import utcnow
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
        if Account.query.filter_by(organisation_id=context.organisation_id, code=code).first():
            raise LedgerError(f"Account code {code} already exists")
        account = Account(
            organisation_id=context.organisation_id,
            code=code.strip(),
            name=name.strip(),
            account_type=account_type.strip().lower(),
            currency=currency.upper() if currency else None,
            parent_id=parent_id,
        )
        db.session.add(account)
        db.session.commit()
        return account

    @staticmethod
    def post_journal(context: AccessContext, *, journal_date: date, description: str,
                     lines: list[dict], reference: str | None = None,
                     source_module: str = "ledger", source_reference: str | None = None,
                     metadata: dict | None = None):
        if not context.can("ledger.journals.post"):
            raise PermissionError("ledger.journals.post")
        if not context.organisation_id:
            raise LedgerError("An organisation is required")
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

        db.session.commit()
        return journal

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
