from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.banking.models import BankAccount, BankTransaction
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class BankingService:
    @staticmethod
    def list_accounts(context: AccessContext):
        return BankAccount.query.filter_by(
            organisation_id=context.organisation_id, is_active=True
        ).order_by(BankAccount.name.asc()).all()

    @staticmethod
    def create_account(context: AccessContext, *, name: str, institution: str | None,
                       currency: str, ledger_account_id: str | None):
        if not context.can("banking.write"):
            raise PermissionError("banking.write")
        row = BankAccount(
            organisation_id=context.organisation_id,
            name=name.strip(),
            institution=(institution or "").strip() or None,
            currency=(currency or "GBP").upper(),
            ledger_account_id=ledger_account_id or None,
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="banking",
            action="bank_account_created",
            entity_type="bank_account",
            entity_id=row.id,
            detail={
                "name": row.name,
                "institution": row.institution,
                "currency": row.currency,
                "ledger_account_id": row.ledger_account_id,
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def list_transactions(context: AccessContext, limit: int = 100):
        return (
            BankTransaction.query.join(BankAccount)
            .filter(BankAccount.organisation_id == context.organisation_id)
            .order_by(BankTransaction.transaction_date.desc(), BankTransaction.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def add_transaction(context: AccessContext, *, bank_account_id: str, transaction_date,
                        description: str, amount, external_id: str | None = None,
                        raw_payload: dict | None = None):
        if not context.can("banking.write"):
            raise PermissionError("banking.write")
        account = db.session.get(BankAccount, bank_account_id)
        if not account or account.organisation_id != context.organisation_id:
            raise ValueError("Invalid bank account")
        row = BankTransaction(
            bank_account_id=account.id,
            transaction_date=transaction_date,
            description=description.strip(),
            amount=Decimal(str(amount)).quantize(Decimal("0.01")),
            external_id=external_id,
            raw_payload=raw_payload or {},
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="banking",
            action="bank_transaction_added",
            entity_type="bank_transaction",
            entity_id=row.id,
            detail={
                "bank_account_id": account.id,
                "transaction_date": str(row.transaction_date),
                "description": row.description,
                "amount": str(row.amount),
                "external_id": row.external_id,
            },
        )
        db.session.commit()
        return row
