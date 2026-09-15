from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow
from ledgerone.models.ledger import Account
from ledgerone.modules.sales.models import Customer, SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.tax.services import TaxService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.posting import workflow_submission_context
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.currency import organisation_base_currency
from ledgerone.services.payment_terms import PaymentTermsService


class SalesInvoiceWorkflowService:
    """Prepare customer invoices for human review before creating AR accounting."""

    ENTITY_TYPE = "sales_invoice"

    @staticmethod
    def _money(value) -> Decimal:
        try:
            return Decimal(str(value or 0)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise WorkflowError(f"Invalid monetary value: {value}") from exc

    @staticmethod
    def _pending_number_exists(organisation_id: str, invoice_number: str) -> bool:
        rows = WorkflowInstance.query.filter_by(
            organisation_id=organisation_id,
            entity_type=SalesInvoiceWorkflowService.ENTITY_TYPE,
        ).filter(WorkflowInstance.status.notin_(["rejected", "posted"])).all()
        target = invoice_number.casefold()
        for row in rows:
            payload = (row.metadata_json or {}).get("sales_invoice_request") or {}
            if str(payload.get("invoice_number") or "").casefold() == target:
                return True
        return False

    @staticmethod
    def _validate_request(
        context: AccessContext,
        *,
        customer_id: str,
        invoice_number: str,
        invoice_date: date,
        due_date: date | None,
        description: str,
        amount,
        receivable_account_id: str,
        revenue_account_id: str,
        currency: str,
        tax_code_id: str | None,
    ) -> tuple[dict, Decimal]:
        if not context.organisation_id:
            raise WorkflowError("An organisation is required")

        clean_number = (invoice_number or "").strip()
        if not clean_number:
            raise WorkflowError("Invoice number is required")
        if SalesInvoice.query.filter_by(
            organisation_id=context.organisation_id,
            invoice_number=clean_number,
        ).first():
            raise WorkflowError("Invoice number already exists")
        if SalesInvoiceWorkflowService._pending_number_exists(context.organisation_id, clean_number):
            raise WorkflowError("Invoice number already exists in an open workflow")

        customer = db.session.get(Customer, customer_id)
        if not customer or customer.organisation_id != context.organisation_id or not customer.is_active:
            raise WorkflowError("Invalid or inactive customer")

        net_amount = SalesInvoiceWorkflowService._money(amount)
        if net_amount <= 0:
            raise WorkflowError("Invoice amount must be greater than zero")

        effective_due = due_date or PaymentTermsService.customer_due_date(
            context.organisation_id,
            invoice_date,
            customer.payment_terms_days,
        )
        if effective_due < invoice_date:
            raise WorkflowError("Invoice due date cannot be before the invoice date")

        receivable = db.session.get(Account, receivable_account_id)
        revenue = db.session.get(Account, revenue_account_id)
        if (
            not receivable
            or receivable.organisation_id != context.organisation_id
            or not receivable.is_active
            or receivable.account_type != "asset"
        ):
            raise WorkflowError("Receivables account must be an active asset account")
        if (
            not revenue
            or revenue.organisation_id != context.organisation_id
            or not revenue.is_active
            or revenue.account_type != "income"
        ):
            raise WorkflowError("Revenue account must be an active income account")

        base_currency = organisation_base_currency(context)
        clean_currency = (currency or base_currency).strip().upper()
        if clean_currency != base_currency:
            raise WorkflowError(
                "Multi-currency accounting is not yet enabled for this organisation. "
                f"Sales invoice uses {clean_currency}, but the organisation base currency is {base_currency}."
            )

        tax_code = TaxService.code_for_use(context, tax_code_id, "sales")
        tax_amount = TaxService.tax_amount(net_amount, tax_code)
        total = net_amount + tax_amount

        payload = {
            "customer_id": customer.id,
            "customer_name": customer.name,
            "invoice_number": clean_number,
            "invoice_date": invoice_date.isoformat(),
            "due_date": effective_due.isoformat(),
            "description": (description or "").strip() or "Sales",
            "amount": str(net_amount),
            "tax_amount": str(tax_amount),
            "total": str(total),
            "currency": clean_currency,
            "receivable_account_id": receivable.id,
            "receivable_account_code": receivable.code,
            "receivable_account_name": receivable.name,
            "revenue_account_id": revenue.id,
            "revenue_account_code": revenue.code,
            "revenue_account_name": revenue.name,
            "tax_code_id": tax_code.id if tax_code else None,
            "tax_code": tax_code.code if tax_code else None,
        }
        return payload, total

    @staticmethod
    def create_request(
        context: AccessContext,
        *,
        customer_id: str,
        invoice_number: str,
        invoice_date: date,
        due_date: date | None,
        description: str,
        amount,
        receivable_account_id: str,
        revenue_account_id: str,
        currency: str = "GBP",
        tax_code_id: str | None = None,
        workflow_definition_id: str | None = None,
        source_module: str = "sales",
        source_reference: str | None = None,
        metadata: dict | None = None,
    ) -> WorkflowInstance:
        submission_context = workflow_submission_context(context, "sales.write")
        payload, total = SalesInvoiceWorkflowService._validate_request(
            context,
            customer_id=customer_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            description=description,
            amount=amount,
            receivable_account_id=receivable_account_id,
            revenue_account_id=revenue_account_id,
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
                "sales_invoice_request": payload,
            }
        )
        workflow = WorkflowService.start(
            submission_context,
            entity_type=SalesInvoiceWorkflowService.ENTITY_TYPE,
            entity_id=request_id,
            title=f"Invoice {payload['invoice_number']} - {payload['customer_name']}",
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
            module_id="sales",
            action="sales_invoice_workflow_submitted",
            entity_type="sales_invoice_request",
            entity_id=request_id,
            detail={
                "workflow_instance_id": workflow.id,
                "invoice_number": payload["invoice_number"],
                "customer_id": payload["customer_id"],
                "total": payload["total"],
                "status": workflow.status,
                "proposal_source_module": source_module,
            },
        )
        db.session.commit()
        return workflow

    @staticmethod
    def request_payload(instance: WorkflowInstance) -> dict:
        return dict((instance.metadata_json or {}).get("sales_invoice_request") or {})

    @staticmethod
    def _assert_reviewed_total_still_valid(
        context: AccessContext,
        instance: WorkflowInstance,
        payload: dict,
    ) -> None:
        net_amount = SalesInvoiceWorkflowService._money(payload.get("amount"))
        tax_code = TaxService.code_for_use(context, payload.get("tax_code_id"), "sales")
        current_tax = TaxService.tax_amount(net_amount, tax_code)
        current_total = net_amount + current_tax
        reviewed_total = SalesInvoiceWorkflowService._money(instance.amount)
        if current_total != reviewed_total:
            raise WorkflowError(
                "The invoice tax/total has changed since workflow review. Return the item for review before posting."
            )

    @staticmethod
    def post_from_action(context: AccessContext, action_id: str) -> SalesInvoice:
        if not context.can("workflows.post"):
            raise PermissionError("workflows.post")
        if not context.can("sales.write"):
            raise PermissionError("sales.write")

        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open posting action not found")
        if action.action_type != "post":
            raise WorkflowError("This user action is not a posting action")
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")

        instance = action.workflow_instance
        if instance.entity_type != SalesInvoiceWorkflowService.ENTITY_TYPE or instance.status != "ready_to_post":
            raise WorkflowError("Sales invoice workflow is not ready for posting")
        payload = SalesInvoiceWorkflowService.request_payload(instance)
        if not payload:
            raise WorkflowError("Sales invoice workflow payload is missing")
        if (instance.metadata_json or {}).get("posted_sales_invoice_id"):
            raise WorkflowError("Sales invoice workflow has already been posted")

        SalesInvoiceWorkflowService._assert_reviewed_total_still_valid(context, instance, payload)
        invoice = SalesService.create_invoice(
            context,
            customer_id=payload["customer_id"],
            invoice_number=payload["invoice_number"],
            invoice_date=date.fromisoformat(payload["invoice_date"]),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
            description=payload.get("description") or "Sales",
            amount=payload["amount"],
            receivable_account_id=payload["receivable_account_id"],
            revenue_account_id=payload["revenue_account_id"],
            currency=payload["currency"],
            tax_code_id=payload.get("tax_code_id"),
            metadata={
                "workflow_instance_id": instance.id,
                "sales_invoice_request_id": instance.entity_id,
                "workflow_originator_user_id": instance.originator_user_id,
                "proposal_source_module": (instance.metadata_json or {}).get("proposal_source_module"),
            },
            commit=False,
        )

        instance.status = "posted"
        instance.completed_at = utcnow()
        instance.metadata_json = {
            **(instance.metadata_json or {}),
            "posted_sales_invoice_id": invoice.id,
            "posted_journal_id": invoice.posted_journal_id,
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
            module_id="sales",
            action="sales_invoice_workflow_posted",
            entity_type="sales_invoice_request",
            entity_id=instance.entity_id,
            detail={
                "workflow_instance_id": instance.id,
                "sales_invoice_id": invoice.id,
                "journal_id": invoice.posted_journal_id,
                "invoice_number": invoice.invoice_number,
                "customer_id": invoice.customer_id,
                "total": str(invoice.total),
            },
        )
        db.session.commit()
        return invoice
