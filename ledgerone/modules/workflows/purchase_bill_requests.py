from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.models import PurchaseBill, Supplier
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.posting import workflow_submission_context
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.currency import organisation_base_currency
from ledgerone.services.ledger import LedgerService
from ledgerone.services.payment_terms import PaymentTermsService


class PurchaseBillWorkflowService:
    """Prepare supplier bills for workflow review before creating accounting records."""

    ENTITY_TYPE = "purchase_bill"

    @staticmethod
    def _money(value) -> Decimal:
        try:
            return Decimal(str(value or 0)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise WorkflowError(f"Invalid monetary value: {value}") from exc

    @staticmethod
    def _pending_number_exists(organisation_id: str, bill_number: str) -> bool:
        rows = WorkflowInstance.query.filter_by(
            organisation_id=organisation_id,
            entity_type=PurchaseBillWorkflowService.ENTITY_TYPE,
        ).filter(WorkflowInstance.status.notin_(["rejected", "posted", "superseded"])).all()
        target = bill_number.casefold()
        for row in rows:
            payload = (row.metadata_json or {}).get("purchase_bill_request") or {}
            if str(payload.get("bill_number") or "").casefold() == target:
                return True
        return False

    @staticmethod
    def _validate_request(
        context: AccessContext,
        *,
        supplier_id: str,
        bill_number: str,
        bill_date: date,
        due_date: date | None,
        tax_point: date | None = None,
        description: str = "Purchase",
        amount,
        payable_account_id: str,
        expense_account_id: str,
        currency: str,
        tax_code_id: str | None,
    ) -> tuple[dict, Decimal]:
        if not context.organisation_id:
            raise WorkflowError("An organisation is required")
        LedgerService.assert_posting_date_open(context, bill_date)
        clean_number = (bill_number or "").strip()
        if not clean_number:
            raise WorkflowError("Bill number is required")
        if PurchaseBill.query.filter_by(
            organisation_id=context.organisation_id,
            bill_number=clean_number,
        ).first():
            raise WorkflowError("Bill number already exists")
        if PurchaseBillWorkflowService._pending_number_exists(context.organisation_id, clean_number):
            raise WorkflowError("Bill number already exists in an open workflow")
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier or supplier.organisation_id != context.organisation_id or not supplier.is_active:
            raise WorkflowError("Invalid or inactive supplier")
        net_amount = PurchaseBillWorkflowService._money(amount)
        if net_amount <= 0:
            raise WorkflowError("Bill amount must be greater than zero")
        effective_due = due_date or PaymentTermsService.supplier_due_date(
            context.organisation_id,
            bill_date,
            supplier.payment_terms_days,
        )
        if effective_due < bill_date:
            raise WorkflowError("Bill due date cannot be before the bill date")
        payable = db.session.get(Account, payable_account_id)
        expense = db.session.get(Account, expense_account_id)
        if (
            not payable
            or payable.organisation_id != context.organisation_id
            or not payable.is_active
            or payable.account_type != "liability"
        ):
            raise WorkflowError("Payables account must be an active liability account")
        if (
            not expense
            or expense.organisation_id != context.organisation_id
            or not expense.is_active
            or expense.account_type != "expense"
        ):
            raise WorkflowError("Expense account must be an active expense account")
        base_currency = organisation_base_currency(context)
        clean_currency = (currency or base_currency).strip().upper()
        if clean_currency != base_currency:
            raise WorkflowError(
                "Multi-currency accounting is not yet enabled for this organisation. "
                f"Purchase bill uses {clean_currency}, but the organisation base currency is {base_currency}."
            )
        tax_code = TaxService.code_for_use(context, tax_code_id, "purchase")
        effective_tax_point = tax_point or bill_date
        if tax_code:
            TaxService.assert_tax_point_open(context, effective_tax_point)
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        total = net_amount + tax_amount
        payload = {
            "supplier_id": supplier.id,
            "supplier_name": supplier.name,
            "bill_number": clean_number,
            "bill_date": bill_date.isoformat(),
            "tax_point": effective_tax_point.isoformat(),
            "due_date": effective_due.isoformat(),
            "description": (description or "").strip() or "Purchase",
            "amount": str(net_amount),
            "tax_amount": str(tax_amount),
            "total": str(total),
            "currency": clean_currency,
            "payable_account_id": payable.id,
            "payable_account_code": payable.code,
            "payable_account_name": payable.name,
            "expense_account_id": expense.id,
            "expense_account_code": expense.code,
            "expense_account_name": expense.name,
            "tax_code_id": tax_code.id if tax_code else None,
            "tax_code": tax_code.code if tax_code else None,
        }
        return payload, total

    @staticmethod
    def create_request(
        context: AccessContext,
        *,
        supplier_id: str,
        bill_number: str,
        bill_date: date,
        due_date: date | None,
        description: str,
        amount,
        payable_account_id: str,
        expense_account_id: str,
        currency: str = "GBP",
        tax_code_id: str | None = None,
        tax_point: date | None = None,
        workflow_definition_id: str | None = None,
        source_module: str = "purchases",
        source_reference: str | None = None,
        metadata: dict | None = None,
    ) -> WorkflowInstance:
        submission_context = workflow_submission_context(context, "purchases.write")
        payload, total = PurchaseBillWorkflowService._validate_request(
            context,
            supplier_id=supplier_id,
            bill_number=bill_number,
            bill_date=bill_date,
            due_date=due_date,
            tax_point=tax_point,
            description=description,
            amount=amount,
            payable_account_id=payable_account_id,
            expense_account_id=expense_account_id,
            currency=currency,
            tax_code_id=tax_code_id,
        )
        request_id = new_id()
        request_metadata = dict(metadata or {})
        request_metadata.update(
            {
                "create_post_action": True,
                "proposal_source_module": source_module,
                "source_reference": source_reference,
                "purchase_bill_request": payload,
            }
        )
        workflow = WorkflowService.start(
            submission_context,
            entity_type=PurchaseBillWorkflowService.ENTITY_TYPE,
            entity_id=request_id,
            title=f"Bill {payload['bill_number']} - {payload['supplier_name']}",
            amount=total,
            currency=payload["currency"],
            source_module=source_module,
            metadata=request_metadata,
            definition_id=workflow_definition_id,
            originator_user_id=context.user_id,
            create_post_action=True,
            commit=False,
        )
        record_audit_event(
            context,
            module_id="purchases",
            action="purchase_bill_workflow_submitted",
            entity_type="purchase_bill_request",
            entity_id=request_id,
            detail={
                "workflow_instance_id": workflow.id,
                "bill_number": payload["bill_number"],
                "supplier_id": payload["supplier_id"],
                "total": payload["total"],
                "status": workflow.status,
                "proposal_source_module": source_module,
            },
        )
        db.session.commit()
        return workflow

    @staticmethod
    def request_payload(instance: WorkflowInstance) -> dict:
        return dict((instance.metadata_json or {}).get("purchase_bill_request") or {})

    @staticmethod
    def _assert_reviewed_total_still_valid(context: AccessContext, instance: WorkflowInstance, payload: dict) -> None:
        net_amount = PurchaseBillWorkflowService._money(payload.get("amount"))
        tax_code = TaxService.code_for_use(context, payload.get("tax_code_id"), "purchase")
        current_tax = TaxService.tax_amount(net_amount, tax_code)
        current_total = net_amount + current_tax
        reviewed_total = PurchaseBillWorkflowService._money(instance.amount)
        if current_total != reviewed_total:
            raise WorkflowError(
                "The bill tax/total has changed since workflow review. Return the item for review before posting."
            )

    @staticmethod
    def post_from_action(context: AccessContext, action_id: str) -> PurchaseBill:
        if not context.can("workflows.post"):
            raise PermissionError("workflows.post")
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open posting action not found")
        if action.action_type != "post":
            raise WorkflowError("This user action is not a posting action")
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")
        instance = action.workflow_instance
        if instance.entity_type != PurchaseBillWorkflowService.ENTITY_TYPE or instance.status != "ready_to_post":
            raise WorkflowError("Purchase bill workflow is not ready for posting")
        payload = PurchaseBillWorkflowService.request_payload(instance)
        if not payload:
            raise WorkflowError("Purchase bill workflow payload is missing")
        if (instance.metadata_json or {}).get("posted_purchase_bill_id"):
            raise WorkflowError("Purchase bill workflow has already been posted")
        PurchaseBillWorkflowService._assert_reviewed_total_still_valid(context, instance, payload)
        bill = PurchasesService.create_bill(
            context,
            supplier_id=payload["supplier_id"],
            bill_number=payload["bill_number"],
            bill_date=date.fromisoformat(payload["bill_date"]),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
            tax_point=date.fromisoformat(payload["tax_point"]) if payload.get("tax_point") else None,
            description=payload.get("description") or "Purchase",
            amount=payload["amount"],
            payable_account_id=payload["payable_account_id"],
            expense_account_id=payload["expense_account_id"],
            currency=payload["currency"],
            tax_code_id=payload.get("tax_code_id"),
            metadata={
                "workflow_instance_id": instance.id,
                "purchase_bill_request_id": instance.entity_id,
                "workflow_originator_user_id": instance.originator_user_id,
                "proposal_source_module": (instance.metadata_json or {}).get("proposal_source_module"),
            },
            commit=False,
        )
        instance.status = "posted"
        instance.completed_at = utcnow()
        instance.metadata_json = {
            **(instance.metadata_json or {}),
            "posted_purchase_bill_id": bill.id,
            "posted_journal_id": bill.posted_journal_id,
        }
        action.status = "completed"
        action.decision = "posted"
        action.completed_by_user_id = context.user_id
        action.completed_at = utcnow()
        for other in instance.actions:
            if other.id != action.id and other.status == "open":
                other.status = "cancelled"
        record_audit_event(
            context,
            module_id="purchases",
            action="purchase_bill_workflow_posted",
            entity_type="purchase_bill_request",
            entity_id=instance.entity_id,
            detail={
                "workflow_instance_id": instance.id,
                "purchase_bill_id": bill.id,
                "journal_id": bill.posted_journal_id,
                "bill_number": bill.bill_number,
                "supplier_id": bill.supplier_id,
                "total": str(bill.total),
            },
        )
        db.session.commit()
        return bill
