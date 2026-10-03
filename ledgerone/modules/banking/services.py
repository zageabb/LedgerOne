from datetime import timedelta
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.modules.banking.models import BankAccount, BankReconciliation, BankTransaction
from ledgerone.services.account_roles import PostingAccountService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService


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
        name = (name or "").strip()
        if not name:
            raise ValueError("Bank account name is required")
        ledger_account = None
        if ledger_account_id:
            ledger_account = PostingAccountService.validate(
                context, ledger_account_id, "bank"
            )
        row = BankAccount(
            organisation_id=context.organisation_id,
            name=name,
            institution=(institution or "").strip() or None,
            currency=(currency or "GBP").upper(),
            ledger_account_id=ledger_account.id if ledger_account else None,
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
    def list_transactions(context: AccessContext, limit: int = 100, *, status: str | None = None):
        query = (
            BankTransaction.query.join(BankAccount)
            .filter(BankAccount.organisation_id == context.organisation_id)
        )
        if status:
            query = query.filter(BankTransaction.status == status)
        return (
            query.order_by(BankTransaction.transaction_date.desc(), BankTransaction.created_at.desc())
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
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
        if value == 0:
            raise ValueError("Bank transaction amount cannot be zero")
        row = BankTransaction(
            bank_account_id=account.id,
            transaction_date=transaction_date,
            description=(description or "").strip() or "Bank transaction",
            amount=value,
            external_id=(external_id or "").strip() or None,
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

    @staticmethod
    def _transaction(context: AccessContext, transaction_id: str) -> BankTransaction:
        row = db.session.get(BankTransaction, transaction_id)
        if not row or row.bank_account.organisation_id != context.organisation_id:
            raise ValueError("Bank transaction not found")
        return row

    @staticmethod
    def _bank_line_matches(transaction: BankTransaction, journal: Journal) -> bool:
        bank_account = transaction.bank_account
        if not bank_account.ledger_account_id:
            return False
        amount = Decimal(transaction.amount).quantize(Decimal("0.01"))
        expected = abs(amount)
        for line in journal.lines:
            if line.account_id != bank_account.ledger_account_id:
                continue
            debit = Decimal(line.debit or 0).quantize(Decimal("0.01"))
            credit = Decimal(line.credit or 0).quantize(Decimal("0.01"))
            if amount > 0 and debit == expected and credit == 0:
                return True
            if amount < 0 and credit == expected and debit == 0:
                return True
        return False

    @staticmethod
    def reconciliation_candidates(context: AccessContext, transaction_id: str, *, days: int = 7,
                                  limit: int = 25):
        if not context.can("banking.reconcile"):
            raise PermissionError("banking.reconcile")
        transaction = BankingService._transaction(context, transaction_id)
        if not transaction.bank_account.ledger_account_id:
            raise ValueError("Link the bank account to a ledger account before reconciling")
        if transaction.status == "reconciled":
            return []
        start_date = transaction.transaction_date - timedelta(days=max(0, int(days)))
        end_date = transaction.transaction_date + timedelta(days=max(0, int(days)))
        matched_ids = {
            value for (value,) in (
                db.session.query(BankTransaction.matched_journal_id)
                .join(BankAccount)
                .filter(
                    BankAccount.organisation_id == context.organisation_id,
                    BankTransaction.matched_journal_id.isnot(None),
                )
                .all()
            ) if value
        }
        rows = (
            Journal.query.filter(
                Journal.organisation_id == context.organisation_id,
                Journal.status == "posted",
                Journal.journal_date >= start_date,
                Journal.journal_date <= end_date,
            )
            .order_by(
                db.func.abs(db.func.julianday(Journal.journal_date) - db.func.julianday(transaction.transaction_date)).asc()
                if db.engine.dialect.name == "sqlite" else Journal.journal_date.desc(),
                Journal.created_at.desc(),
            )
            .limit(250)
            .all()
        )
        candidates = [
            row for row in rows
            if row.id not in matched_ids and BankingService._bank_line_matches(transaction, row)
        ]
        return candidates[:max(1, min(int(limit), 100))]

    @staticmethod
    def match_transaction(context: AccessContext, transaction_id: str, journal_id: str):
        if not context.can("banking.reconcile"):
            raise PermissionError("banking.reconcile")
        transaction = BankingService._transaction(context, transaction_id)
        if transaction.status == "reconciled" or transaction.matched_journal_id:
            raise ValueError("Bank transaction is already reconciled")
        journal = db.session.get(Journal, journal_id)
        if not journal or journal.organisation_id != context.organisation_id or journal.status != "posted":
            raise ValueError("Journal not found")
        already_used = (
            BankTransaction.query.join(BankAccount)
            .filter(
                BankAccount.organisation_id == context.organisation_id,
                BankTransaction.matched_journal_id == journal.id,
            )
            .first()
        )
        if already_used:
            raise ValueError("Journal is already matched to another bank transaction")
        if not BankingService._bank_line_matches(transaction, journal):
            raise ValueError("Journal does not contain a matching bank-account amount")
        transaction.matched_journal_id = journal.id
        transaction.status = "reconciled"
        record_audit_event(
            context,
            module_id="banking",
            action="bank_transaction_matched",
            entity_type="bank_transaction",
            entity_id=transaction.id,
            detail={"journal_id": journal.id, "amount": str(transaction.amount)},
        )
        db.session.commit()
        return transaction

    @staticmethod
    def post_and_match(context: AccessContext, transaction_id: str, *, offset_account_id: str,
                       description: str | None = None, reference: str | None = None):
        if not context.can("banking.reconcile"):
            raise PermissionError("banking.reconcile")
        transaction = BankingService._transaction(context, transaction_id)
        if transaction.status == "reconciled" or transaction.matched_journal_id:
            raise ValueError("Bank transaction is already reconciled")
        bank_account = transaction.bank_account
        if not bank_account.ledger_account_id:
            raise ValueError("Link the bank account to a ledger account before reconciling")
        PostingAccountService.validate(context, bank_account.ledger_account_id, "bank")
        offset_account = db.session.get(Account, offset_account_id)
        if not offset_account or offset_account.organisation_id != context.organisation_id:
            raise ValueError("Invalid offset account")
        if offset_account.id == bank_account.ledger_account_id:
            raise ValueError("Offset account must be different from the linked bank account")

        amount = Decimal(transaction.amount).quantize(Decimal("0.01"))
        value = abs(amount)
        if amount > 0:
            lines = [
                {
                    "account_id": bank_account.ledger_account_id,
                    "debit": value,
                    "credit": 0,
                    "description": transaction.description,
                    "currency": bank_account.currency,
                    "dimensions": {"bank_transaction_id": transaction.id},
                },
                {
                    "account_id": offset_account.id,
                    "debit": 0,
                    "credit": value,
                    "description": description or transaction.description,
                    "currency": bank_account.currency,
                    "dimensions": {"bank_transaction_id": transaction.id},
                },
            ]
        else:
            lines = [
                {
                    "account_id": offset_account.id,
                    "debit": value,
                    "credit": 0,
                    "description": description or transaction.description,
                    "currency": bank_account.currency,
                    "dimensions": {"bank_transaction_id": transaction.id},
                },
                {
                    "account_id": bank_account.ledger_account_id,
                    "debit": 0,
                    "credit": value,
                    "description": transaction.description,
                    "currency": bank_account.currency,
                    "dimensions": {"bank_transaction_id": transaction.id},
                },
            ]
        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=transaction.transaction_date,
                description=(description or transaction.description).strip(),
                reference=(reference or transaction.external_id or f"BANK-{transaction.id[:8]}")[:120],
                lines=lines,
                source_module="banking",
                source_reference=transaction.id,
                metadata={"bank_transaction_id": transaction.id, "reconciliation": True},
                commit=False,
                enforce_permission=False,
            )
            transaction.matched_journal_id = journal.id
            transaction.status = "reconciled"
            record_audit_event(
                context,
                module_id="banking",
                action="bank_transaction_posted_and_matched",
                entity_type="bank_transaction",
                entity_id=transaction.id,
                detail={
                    "journal_id": journal.id,
                    "offset_account_id": offset_account.id,
                    "amount": str(transaction.amount),
                },
            )
            db.session.commit()
            return transaction, journal
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def unmatch_transaction(context: AccessContext, transaction_id: str):
        if not context.can("banking.reconcile"):
            raise PermissionError("banking.reconcile")
        transaction = BankingService._transaction(context, transaction_id)
        if transaction.status != "reconciled" or not transaction.matched_journal_id:
            raise ValueError("Bank transaction is not reconciled")
        journal = db.session.get(Journal, transaction.matched_journal_id)
        if journal and journal.source_module == "banking" and journal.source_reference == transaction.id:
            raise ValueError(
                "This reconciliation created a posted journal. Reverse that journal before changing the reconciliation."
            )
        previous_journal_id = transaction.matched_journal_id
        transaction.matched_journal_id = None
        transaction.status = "unreconciled"
        record_audit_event(
            context,
            module_id="banking",
            action="bank_transaction_unmatched",
            entity_type="bank_transaction",
            entity_id=transaction.id,
            detail={"previous_journal_id": previous_journal_id},
        )
        db.session.commit()
        return transaction


    @staticmethod
    def _identity(context: AccessContext) -> str:
        if context.user_id:
            return f"user:{context.user_id}"
        if context.api_key_id:
            return f"api_key:{context.api_key_id}"
        return context.identity_type or "system"

    @staticmethod
    def _money(value) -> Decimal:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))

    @staticmethod
    def _ledger_balance_at(bank_account: BankAccount, end_date):
        if not bank_account.ledger_account_id:
            raise ValueError("Link the bank account to a ledger account before creating a formal reconciliation")
        value = (
            db.session.query(
                db.func.coalesce(db.func.sum(JournalLine.debit - JournalLine.credit), 0)
            )
            .join(Journal, Journal.id == JournalLine.journal_id)
            .filter(
                Journal.organisation_id == bank_account.organisation_id,
                Journal.status == "posted",
                Journal.journal_date >= start_date,
                Journal.journal_date <= end_date,
                JournalLine.account_id == bank_account.ledger_account_id,
            )
            .scalar()
        )
        return BankingService._money(value)

    @staticmethod
    def _formal_snapshot(context: AccessContext, bank_account: BankAccount, start_date, end_date):
        transactions = (
            BankTransaction.query.filter(
                BankTransaction.bank_account_id == bank_account.id,
                BankTransaction.transaction_date >= start_date,
                BankTransaction.transaction_date <= end_date,
            )
            .order_by(BankTransaction.transaction_date.asc(), BankTransaction.created_at.asc())
            .all()
        )
        matched_journal_ids = {
            value
            for (value,) in (
                db.session.query(BankTransaction.matched_journal_id)
                .filter(
                    BankTransaction.bank_account_id == bank_account.id,
                    BankTransaction.transaction_date <= end_date,
                    BankTransaction.matched_journal_id.isnot(None),
                )
                .all()
            )
            if value
        }
        statement_rows = []
        unmatched_statement_total = Decimal("0.00")
        for row in transactions:
            amount = BankingService._money(row.amount)
            if not row.matched_journal_id:
                unmatched_statement_total += amount
            statement_rows.append(
                {
                    "id": row.id,
                    "date": row.transaction_date.isoformat(),
                    "description": row.description,
                    "amount": str(amount),
                    "status": row.status,
                    "matched_journal_id": row.matched_journal_id,
                    "external_id": row.external_id,
                }
            )

        book_rows = (
            db.session.query(JournalLine, Journal)
            .join(Journal, Journal.id == JournalLine.journal_id)
            .filter(
                Journal.organisation_id == context.organisation_id,
                Journal.status == "posted",
                Journal.journal_date <= end_date,
                JournalLine.account_id == bank_account.ledger_account_id,
            )
            .order_by(Journal.journal_date.asc(), Journal.created_at.asc())
            .all()
        )
        outstanding_book = []
        outstanding_book_total = Decimal("0.00")
        for line, journal in book_rows:
            if journal.id in matched_journal_ids:
                continue
            net = BankingService._money(line.debit) - BankingService._money(line.credit)
            if not net:
                continue
            outstanding_book_total += net
            outstanding_book.append(
                {
                    "journal_id": journal.id,
                    "date": journal.journal_date.isoformat(),
                    "reference": journal.reference,
                    "description": journal.description,
                    "amount": str(net),
                }
            )

        return {
            "statement_transactions": statement_rows,
            "outstanding_book_items": outstanding_book,
            "unmatched_statement_total": BankingService._money(unmatched_statement_total),
            "outstanding_book_total": BankingService._money(outstanding_book_total),
            "ledger_balance": BankingService._ledger_balance_at(bank_account, end_date),
        }

    @staticmethod
    def _recalculate_formal(row: BankReconciliation, snapshot: dict):
        unmatched = BankingService._money(snapshot["unmatched_statement_total"])
        outstanding = BankingService._money(snapshot["outstanding_book_total"])
        ledger_balance = BankingService._money(snapshot["ledger_balance"])
        explained = BankingService._money(row.explained_difference)
        adjusted_statement = (
            BankingService._money(row.statement_closing_balance)
            - unmatched
            + outstanding
            + explained
        )
        residual = BankingService._money(adjusted_statement - ledger_balance)
        row.ledger_balance = ledger_balance
        row.unmatched_statement_total = unmatched
        row.outstanding_book_total = outstanding
        row.residual_difference = residual
        row.snapshot_json = {
            **snapshot,
            "statement_opening_balance": str(BankingService._money(row.statement_opening_balance)),
            "statement_closing_balance": str(BankingService._money(row.statement_closing_balance)),
            "explained_difference": str(explained),
            "adjusted_statement_balance": str(BankingService._money(adjusted_statement)),
            "residual_difference": str(residual),
        }

    @staticmethod
    def list_formal_reconciliations(context: AccessContext, bank_account_id: str | None = None):
        query = BankReconciliation.query.filter_by(organisation_id=context.organisation_id)
        if bank_account_id:
            query = query.filter(BankReconciliation.bank_account_id == bank_account_id)
        return query.order_by(
            BankReconciliation.statement_end_date.desc(),
            BankReconciliation.created_at.desc(),
        ).all()

    @staticmethod
    def get_formal_reconciliation(context: AccessContext, reconciliation_id: str):
        row = db.session.get(BankReconciliation, reconciliation_id)
        if not row or row.organisation_id != context.organisation_id:
            raise ValueError("Bank reconciliation not found")
        return row

    @staticmethod
    def create_formal_reconciliation(
        context: AccessContext,
        *,
        bank_account_id: str,
        statement_start_date,
        statement_end_date,
        statement_opening_balance,
        statement_closing_balance,
        explained_difference=0,
        explanation: str | None = None,
    ):
        if not context.can("banking.reconcile"):
            raise PermissionError("banking.reconcile")
        if statement_end_date < statement_start_date:
            raise ValueError("Statement end date cannot be before statement start date")
        account = db.session.get(BankAccount, bank_account_id)
        if not account or account.organisation_id != context.organisation_id:
            raise ValueError("Invalid bank account")
        PostingAccountService.validate(context, account.ledger_account_id, "bank")
        snapshot = BankingService._formal_snapshot(
            context, account, statement_start_date, statement_end_date
        )
        row = BankReconciliation(
            organisation_id=context.organisation_id,
            bank_account_id=account.id,
            statement_start_date=statement_start_date,
            statement_end_date=statement_end_date,
            statement_opening_balance=BankingService._money(statement_opening_balance),
            statement_closing_balance=BankingService._money(statement_closing_balance),
            explained_difference=BankingService._money(explained_difference),
            explanation=(explanation or "").strip() or None,
            prepared_by_user_id=context.user_id,
            prepared_identity=BankingService._identity(context),
        )
        BankingService._recalculate_formal(row, snapshot)
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="banking",
            action="bank_reconciliation_prepared",
            entity_type="bank_reconciliation",
            entity_id=row.id,
            detail={
                "bank_account_id": account.id,
                "statement_start_date": statement_start_date.isoformat(),
                "statement_end_date": statement_end_date.isoformat(),
                "statement_closing_balance": str(row.statement_closing_balance),
                "ledger_balance": str(row.ledger_balance),
                "residual_difference": str(row.residual_difference),
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def refresh_formal_reconciliation(
        context: AccessContext,
        reconciliation_id: str,
        *,
        explained_difference=None,
        explanation: str | None = None,
    ):
        if not context.can("banking.reconcile"):
            raise PermissionError("banking.reconcile")
        row = BankingService.get_formal_reconciliation(context, reconciliation_id)
        if row.status != "draft":
            raise ValueError("Finalised bank reconciliation is immutable")
        if explained_difference is not None:
            row.explained_difference = BankingService._money(explained_difference)
        if explanation is not None:
            row.explanation = explanation.strip() or None
        snapshot = BankingService._formal_snapshot(
            context, row.bank_account, row.statement_start_date, row.statement_end_date
        )
        BankingService._recalculate_formal(row, snapshot)
        record_audit_event(
            context,
            module_id="banking",
            action="bank_reconciliation_refreshed",
            entity_type="bank_reconciliation",
            entity_id=row.id,
            detail={
                "ledger_balance": str(row.ledger_balance),
                "unmatched_statement_total": str(row.unmatched_statement_total),
                "outstanding_book_total": str(row.outstanding_book_total),
                "explained_difference": str(row.explained_difference),
                "residual_difference": str(row.residual_difference),
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def finalise_formal_reconciliation(context: AccessContext, reconciliation_id: str):
        if not context.can("banking.reconcile"):
            raise PermissionError("banking.reconcile")
        row = BankingService.get_formal_reconciliation(context, reconciliation_id)
        if row.status != "draft":
            raise ValueError("Bank reconciliation is already finalised")
        snapshot = BankingService._formal_snapshot(
            context, row.bank_account, row.statement_start_date, row.statement_end_date
        )
        BankingService._recalculate_formal(row, snapshot)
        if BankingService._money(row.residual_difference) != Decimal("0.00"):
            raise ValueError(
                f"Bank reconciliation cannot be finalised with residual difference {row.residual_difference}"
            )
        from ledgerone.models.core import utcnow

        row.status = "finalised"
        row.approved_by_user_id = context.user_id
        row.approved_identity = BankingService._identity(context)
        row.approved_at = utcnow()
        row.finalised_at = row.approved_at
        record_audit_event(
            context,
            module_id="banking",
            action="bank_reconciliation_finalised",
            entity_type="bank_reconciliation",
            entity_id=row.id,
            detail={
                "bank_account_id": row.bank_account_id,
                "statement_end_date": row.statement_end_date.isoformat(),
                "statement_closing_balance": str(row.statement_closing_balance),
                "ledger_balance": str(row.ledger_balance),
                "residual_difference": str(row.residual_difference),
                "prepared_by": row.prepared_identity,
                "approved_by": row.approved_identity,
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def formal_reconciliation_evidence(context: AccessContext, reconciliation_id: str) -> dict:
        row = BankingService.get_formal_reconciliation(context, reconciliation_id)
        return {
            "id": row.id,
            "status": row.status,
            "bank_account": {
                "id": row.bank_account.id,
                "name": row.bank_account.name,
                "institution": row.bank_account.institution,
                "currency": row.bank_account.currency,
                "ledger_account_id": row.bank_account.ledger_account_id,
            },
            "statement_start_date": row.statement_start_date.isoformat(),
            "statement_end_date": row.statement_end_date.isoformat(),
            "statement_opening_balance": str(BankingService._money(row.statement_opening_balance)),
            "statement_closing_balance": str(BankingService._money(row.statement_closing_balance)),
            "ledger_balance": str(BankingService._money(row.ledger_balance)),
            "unmatched_statement_total": str(BankingService._money(row.unmatched_statement_total)),
            "outstanding_book_total": str(BankingService._money(row.outstanding_book_total)),
            "explained_difference": str(BankingService._money(row.explained_difference)),
            "residual_difference": str(BankingService._money(row.residual_difference)),
            "explanation": row.explanation,
            "prepared_by": row.prepared_identity,
            "approved_by": row.approved_identity,
            "prepared_at": row.prepared_at.isoformat() if row.prepared_at else None,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "finalised_at": row.finalised_at.isoformat() if row.finalised_at else None,
            "snapshot": row.snapshot_json,
        }
