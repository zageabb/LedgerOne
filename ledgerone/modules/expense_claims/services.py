from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import inspect

from ledgerone.extensions import db
from ledgerone.models.core import utcnow
from ledgerone.models.ledger import Account
from ledgerone.modules.expense_claims.models import ExpenseClaim, ExpenseClaimLine
from ledgerone.modules.tax.models import TaxCode
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


class ExpenseClaimError(ValueError):
    pass


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ExpenseClaimError(f"Invalid monetary value: {value}") from exc


class ExpenseClaimService:
    @staticmethod
    def seed_defaults(organisation_id: str):
        inspector = inspect(db.engine)
        if not inspector.has_table("expense_claims"):
            return
        row = Account.query.filter_by(organisation_id=organisation_id, code="2150").first()
        if row is None:
            db.session.add(
                Account(
                    organisation_id=organisation_id,
                    code="2150",
                    name="Employee Reimbursements",
                    account_type="liability",
                    is_control_account=True,
                )
            )
            db.session.commit()

    @staticmethod
    def list_claims(context: AccessContext, limit: int = 100):
        if not context.can("expense_claims.read"):
            raise PermissionError("expense_claims.read")
        return (
            ExpenseClaim.query.filter_by(organisation_id=context.organisation_id)
            .order_by(ExpenseClaim.claim_date.desc(), ExpenseClaim.created_at.desc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )

    @staticmethod
    def _claim(context: AccessContext, claim_id: str):
        row = db.session.get(ExpenseClaim, claim_id)
        if not row or row.organisation_id != context.organisation_id:
            raise ExpenseClaimError("Expense claim not found")
        return row

    @staticmethod
    def _reimbursement_account(context: AccessContext, account_id: str | None):
        if account_id:
            row = db.session.get(Account, account_id)
        else:
            row = Account.query.filter_by(
                organisation_id=context.organisation_id, code="2150"
            ).first()
        if not row or row.organisation_id != context.organisation_id:
            raise ExpenseClaimError("A reimbursement liability account is required")
        if row.account_type != "liability":
            raise ExpenseClaimError("Reimbursement account must be a liability account")
        return row

    @staticmethod
    def _line_values(context: AccessContext, *, amount, expense_account_id: str, tax_code_id: str | None):
        net_amount = _money(amount)
        if net_amount <= 0:
            raise ExpenseClaimError("Expense amount must be greater than zero")
        expense = db.session.get(Account, expense_account_id)
        if not expense or expense.organisation_id != context.organisation_id:
            raise ExpenseClaimError("Invalid expense account")
        if expense.account_type != "expense":
            raise ExpenseClaimError("Expense claim line must use an expense account")
        tax_code = TaxService.code_for_use(context, tax_code_id, "purchase")
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        return net_amount, tax_amount, expense, tax_code

    @staticmethod
    def _recalculate(claim: ExpenseClaim):
        claim.subtotal = sum((_money(line.net_amount) for line in claim.lines), Decimal("0.00"))
        claim.tax_total = sum((_money(line.tax_amount) for line in claim.lines), Decimal("0.00"))
        claim.total = _money(claim.subtotal) + _money(claim.tax_total)

    @staticmethod
    def create_claim(
        context: AccessContext,
        *,
        claimant_name: str,
        claim_number: str,
        claim_date: date,
        expense_date: date,
        merchant: str | None,
        description: str,
        amount,
        expense_account_id: str,
        reimbursement_account_id: str | None = None,
        currency: str = "GBP",
        tax_code_id: str | None = None,
    ):
        if not context.can("expense_claims.write"):
            raise PermissionError("expense_claims.write")
        claimant_name = (claimant_name or "").strip()
        claim_number = (claim_number or "").strip()
        if not claimant_name:
            raise ExpenseClaimError("Claimant name is required")
        if not claim_number:
            raise ExpenseClaimError("Claim number is required")
        if ExpenseClaim.query.filter_by(
            organisation_id=context.organisation_id, claim_number=claim_number
        ).first():
            raise ExpenseClaimError("Claim number already exists")
        if expense_date > claim_date:
            raise ExpenseClaimError("Expense date cannot be after the claim date")

        reimbursement = ExpenseClaimService._reimbursement_account(
            context, reimbursement_account_id
        )
        net_amount, tax_amount, expense, tax_code = ExpenseClaimService._line_values(
            context,
            amount=amount,
            expense_account_id=expense_account_id,
            tax_code_id=tax_code_id,
        )
        claim = ExpenseClaim(
            organisation_id=context.organisation_id,
            claimant_user_id=context.user_id,
            claimant_name=claimant_name,
            claim_number=claim_number,
            claim_date=claim_date,
            currency=(currency or "GBP").upper()[:3],
            status="draft",
            subtotal=net_amount,
            tax_total=tax_amount,
            total=net_amount + tax_amount,
            reimbursement_account_id=reimbursement.id,
        )
        db.session.add(claim)
        db.session.flush()
        db.session.add(
            ExpenseClaimLine(
                claim_id=claim.id,
                line_number=1,
                expense_date=expense_date,
                merchant=(merchant or "").strip() or None,
                description=(description or "").strip() or "Expense",
                net_amount=net_amount,
                tax_amount=tax_amount,
                tax_code_id=tax_code.id if tax_code else None,
                expense_account_id=expense.id,
                dimensions={"tax_code": tax_code.code} if tax_code else {},
            )
        )
        record_audit_event(
            context,
            module_id="expense_claims",
            action="claim_created",
            entity_type="expense_claim",
            entity_id=claim.id,
            detail={
                "claim_number": claim.claim_number,
                "claimant_name": claim.claimant_name,
                "total": str(claim.total),
            },
        )
        db.session.commit()
        return claim

    @staticmethod
    def add_line(
        context: AccessContext,
        claim_id: str,
        *,
        expense_date: date,
        merchant: str | None,
        description: str,
        amount,
        expense_account_id: str,
        tax_code_id: str | None = None,
    ):
        if not context.can("expense_claims.write"):
            raise PermissionError("expense_claims.write")
        claim = ExpenseClaimService._claim(context, claim_id)
        if claim.status != "draft":
            raise ExpenseClaimError("Lines can only be added to a draft expense claim")
        if expense_date > claim.claim_date:
            raise ExpenseClaimError("Expense date cannot be after the claim date")
        net_amount, tax_amount, expense, tax_code = ExpenseClaimService._line_values(
            context,
            amount=amount,
            expense_account_id=expense_account_id,
            tax_code_id=tax_code_id,
        )
        line = ExpenseClaimLine(
            claim_id=claim.id,
            line_number=len(claim.lines) + 1,
            expense_date=expense_date,
            merchant=(merchant or "").strip() or None,
            description=(description or "").strip() or "Expense",
            net_amount=net_amount,
            tax_amount=tax_amount,
            tax_code_id=tax_code.id if tax_code else None,
            expense_account_id=expense.id,
            dimensions={"tax_code": tax_code.code} if tax_code else {},
        )
        db.session.add(line)
        db.session.flush()
        db.session.expire(claim, ["lines"])
        _ = claim.lines
        ExpenseClaimService._recalculate(claim)
        record_audit_event(
            context,
            module_id="expense_claims",
            action="claim_line_added",
            entity_type="expense_claim",
            entity_id=claim.id,
            detail={"line_number": line.line_number, "line_total": str(net_amount + tax_amount)},
        )
        db.session.commit()
        return line, claim

    @staticmethod
    def submit(context: AccessContext, claim_id: str):
        if not context.can("expense_claims.write"):
            raise PermissionError("expense_claims.write")
        claim = ExpenseClaimService._claim(context, claim_id)
        if claim.status != "draft":
            raise ExpenseClaimError("Only a draft expense claim can be submitted")
        if not claim.lines:
            raise ExpenseClaimError("Expense claim has no lines")
        ExpenseClaimService._recalculate(claim)
        claim.status = "submitted"
        record_audit_event(
            context,
            module_id="expense_claims",
            action="claim_submitted",
            entity_type="expense_claim",
            entity_id=claim.id,
            detail={"total": str(claim.total)},
        )
        db.session.commit()
        return claim

    @staticmethod
    def reject(context: AccessContext, claim_id: str, *, reason: str | None = None):
        if not context.can("expense_claims.approve"):
            raise PermissionError("expense_claims.approve")
        claim = ExpenseClaimService._claim(context, claim_id)
        if claim.status != "submitted":
            raise ExpenseClaimError("Only a submitted expense claim can be rejected")
        claim.status = "rejected"
        claim.metadata_json = {**(claim.metadata_json or {}), "rejection_reason": (reason or "").strip() or None}
        record_audit_event(
            context,
            module_id="expense_claims",
            action="claim_rejected",
            entity_type="expense_claim",
            entity_id=claim.id,
            detail={"reason": (reason or "").strip() or None},
        )
        db.session.commit()
        return claim

    @staticmethod
    def approve_and_post(context: AccessContext, claim_id: str, *, posting_date: date):
        if not context.can("expense_claims.approve"):
            raise PermissionError("expense_claims.approve")
        claim = ExpenseClaimService._claim(context, claim_id)
        if claim.status != "submitted":
            raise ExpenseClaimError("Only a submitted expense claim can be approved")
        if not claim.lines:
            raise ExpenseClaimError("Expense claim has no lines")

        lines = []
        for line in claim.lines:
            dimensions = {
                "expense_claim_id": claim.id,
                "claimant_user_id": claim.claimant_user_id,
            }
            lines.append(
                {
                    "account_id": line.expense_account_id,
                    "debit": _money(line.net_amount),
                    "credit": 0,
                    "description": line.description,
                    "currency": claim.currency,
                    "dimensions": {**dimensions, "tax_code_id": line.tax_code_id},
                }
            )
            tax_amount = _money(line.tax_amount)
            if tax_amount:
                tax_code = db.session.get(TaxCode, line.tax_code_id)
                if (
                    not tax_code
                    or tax_code.organisation_id != context.organisation_id
                    or not tax_code.purchase_tax_account_id
                ):
                    raise ExpenseClaimError("Expense claim tax code has no recoverable VAT account")
                lines.append(
                    {
                        "account_id": tax_code.purchase_tax_account_id,
                        "debit": tax_amount,
                        "credit": 0,
                        "description": f"{tax_code.code} input VAT",
                        "currency": claim.currency,
                        "dimensions": {**dimensions, "tax_code_id": tax_code.id},
                    }
                )

        lines.append(
            {
                "account_id": claim.reimbursement_account_id,
                "debit": 0,
                "credit": _money(claim.total),
                "description": claim.claimant_name,
                "currency": claim.currency,
                "dimensions": {
                    "expense_claim_id": claim.id,
                    "claimant_user_id": claim.claimant_user_id,
                },
            }
        )

        try:
            journal = LedgerService.post_journal(
                context,
                journal_date=posting_date,
                description=f"Expense claim {claim.claim_number} - {claim.claimant_name}",
                reference=claim.claim_number,
                source_module="expense_claims",
                source_reference=claim.id,
                lines=lines,
                commit=False,
            )
            claim.status = "posted"
            claim.approved_at = utcnow()
            claim.approved_by_user_id = context.user_id
            claim.posted_journal_id = journal.id
            record_audit_event(
                context,
                module_id="expense_claims",
                action="claim_approved_posted",
                entity_type="expense_claim",
                entity_id=claim.id,
                detail={"journal_id": journal.id, "posting_date": posting_date.isoformat(), "total": str(claim.total)},
            )
            db.session.commit()
            return claim, journal
        except Exception:
            db.session.rollback()
            raise
