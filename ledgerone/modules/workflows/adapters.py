from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.workflows.models import UserAction
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.context import AccessContext


def _money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01"))) if value is not None else None


def _flat_payload(payload) -> dict:
    if payload is None:
        return {}
    if hasattr(payload, "to_dict"):
        return payload.to_dict(flat=True)
    return dict(payload)


class BaseWorkflowAdapter:
    """Uniform action contract used by the central workflow dispatcher."""

    supports_revision = False

    @classmethod
    def complete_action(
        cls,
        context: AccessContext,
        action_id: str,
        *,
        decision: str,
        comments: str | None = None,
    ):
        action = db.session.get(UserAction, action_id)
        clean_decision = (decision or "approve").strip().lower()
        if (
            cls.supports_revision
            and action
            and action.workflow_instance
            and action.workflow_instance.status == "returned"
            and clean_decision != "reject"
        ):
            raise WorkflowError(
                "Returned accounting proposals must be corrected and resubmitted as a replacement workflow, or rejected."
            )
        return WorkflowService.complete_action(
            context,
            action_id,
            decision=clean_decision,
            comments=comments,
        )


class JournalWorkflowAdapter(BaseWorkflowAdapter):
    supports_revision = True

    @staticmethod
    def post_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.journal_requests import JournalWorkflowService

        return JournalWorkflowService.post_from_action(context, action_id)

    @staticmethod
    def revise_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.revisions import WorkflowRevisionService

        if channel == "browser" and hasattr(payload, "getlist"):
            account_ids = payload.getlist("line_account_id")
            descriptions = payload.getlist("line_description")
            debits = payload.getlist("line_debit")
            credits = payload.getlist("line_credit")
            currency = payload.get("currency") or None
            lines = []
            for index, account_id in enumerate(account_ids):
                lines.append(
                    {
                        "account_id": account_id,
                        "description": descriptions[index] if index < len(descriptions) else None,
                        "debit": debits[index] if index < len(debits) and debits[index] not in (None, "") else 0,
                        "credit": credits[index] if index < len(credits) and credits[index] not in (None, "") else 0,
                        "currency": currency,
                    }
                )
            changes = {
                "journal_date": payload.get("journal_date"),
                "reference": payload.get("reference"),
                "description": payload.get("description"),
                "lines": lines,
            }
        else:
            changes = _flat_payload(payload)
        return WorkflowRevisionService.revise_journal(
            context,
            action_id,
            changes,
            revision_source_module=channel,
        )

    @staticmethod
    def browser_message(row) -> str:
        return f"Journal {row.reference or row.id[:8]} posted to the ledger."

    @staticmethod
    def api_result(row) -> dict:
        return {
            "entity_type": "journal",
            "journal": {
                "id": row.id,
                "journal_date": row.journal_date.isoformat(),
                "reference": row.reference,
                "description": row.description,
                "source_module": row.source_module,
                "source_reference": row.source_reference,
                "total_debit": _money(row.total_debit),
                "total_credit": _money(row.total_credit),
                "status": row.status,
            },
        }


class PurchaseBillWorkflowAdapter(BaseWorkflowAdapter):
    supports_revision = True

    @staticmethod
    def post_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.purchase_bill_requests import PurchaseBillWorkflowService

        return PurchaseBillWorkflowService.post_from_action(context, action_id)

    @staticmethod
    def revise_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.revisions import WorkflowRevisionService

        return WorkflowRevisionService.revise_purchase_bill(
            context,
            action_id,
            _flat_payload(payload),
            revision_source_module=channel,
        )

    @staticmethod
    def browser_message(row) -> str:
        return f"Bill {row.bill_number} posted to Accounts Payable."

    @staticmethod
    def api_result(row) -> dict:
        return {
            "entity_type": "purchase_bill",
            "purchase_bill": {
                "id": row.id,
                "supplier_id": row.supplier_id,
                "bill_number": row.bill_number,
                "bill_date": row.bill_date.isoformat(),
                "due_date": row.due_date.isoformat() if row.due_date else None,
                "currency": row.currency,
                "subtotal": _money(row.subtotal),
                "tax_total": _money(row.tax_total),
                "total": _money(row.total),
                "status": row.status,
                "journal_id": row.posted_journal_id,
            },
        }


class SalesInvoiceWorkflowAdapter(BaseWorkflowAdapter):
    supports_revision = True

    @staticmethod
    def post_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService

        return SalesInvoiceWorkflowService.post_from_action(context, action_id)

    @staticmethod
    def revise_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.revisions import WorkflowRevisionService

        return WorkflowRevisionService.revise_sales_invoice(
            context,
            action_id,
            _flat_payload(payload),
            revision_source_module=channel,
        )

    @staticmethod
    def browser_message(row) -> str:
        return f"Invoice {row.invoice_number} posted to Accounts Receivable."

    @staticmethod
    def api_result(row) -> dict:
        return {
            "entity_type": "sales_invoice",
            "sales_invoice": {
                "id": row.id,
                "customer_id": row.customer_id,
                "invoice_number": row.invoice_number,
                "invoice_date": row.invoice_date.isoformat(),
                "due_date": row.due_date.isoformat() if row.due_date else None,
                "currency": row.currency,
                "subtotal": _money(row.subtotal),
                "tax_total": _money(row.tax_total),
                "total": _money(row.total),
                "status": row.status,
                "journal_id": row.posted_journal_id,
            },
        }


class ExpenseClaimWorkflowAdapter(BaseWorkflowAdapter):
    @staticmethod
    def complete_action(
        context: AccessContext,
        action_id: str,
        *,
        decision: str,
        comments: str | None = None,
    ):
        from ledgerone.modules.workflows.expense_claim_requests import ExpenseClaimWorkflowService

        return ExpenseClaimWorkflowService.complete_action(
            context,
            action_id,
            decision=decision,
            comments=comments,
        )

    @staticmethod
    def post_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.expense_claim_requests import ExpenseClaimWorkflowService

        payload = payload or {}
        posting_date = date.fromisoformat(payload.get("posting_date") or date.today().isoformat())
        return ExpenseClaimWorkflowService.post_from_action(
            context,
            action_id,
            posting_date=posting_date,
        )

    @staticmethod
    def browser_message(row) -> str:
        return f"Expense claim {row.claim_number} approved and posted."

    @staticmethod
    def api_result(row) -> dict:
        return {
            "entity_type": "expense_claim",
            "expense_claim": {
                "id": row.id,
                "claim_number": row.claim_number,
                "claimant_name": row.claimant_name,
                "claim_date": row.claim_date.isoformat(),
                "currency": row.currency,
                "subtotal": _money(row.subtotal),
                "tax_total": _money(row.tax_total),
                "total": _money(row.total),
                "status": row.status,
                "journal_id": row.posted_journal_id,
            },
        }


class ScheduledTransactionWorkflowAdapter(BaseWorkflowAdapter):
    @staticmethod
    def post_action(context: AccessContext, action_id: str, payload=None, *, channel: str = "api"):
        from ledgerone.modules.workflows.services import RecurringTransactionService

        payload = payload or {}
        if payload.get("posting_date"):
            posting_date = date.fromisoformat(payload["posting_date"])
        elif channel == "browser":
            posting_date = date.today()
        else:
            posting_date = None
        return RecurringTransactionService.post_from_action(
            context,
            action_id,
            actual_amount=payload.get("actual_amount") or None,
            posting_date=posting_date,
        )

    @staticmethod
    def browser_message(row) -> str:
        return f"{row.template.name} posted to the ledger."

    @staticmethod
    def api_result(row) -> dict:
        # Preserve the original Scheduled Transactions API response shape.
        return {
            "id": row.id,
            "template_id": row.template_id,
            "scheduled_date": row.scheduled_date.isoformat(),
            "transaction_type": row.transaction_type,
            "description": row.description,
            "expected_amount": _money(row.expected_amount),
            "actual_amount": _money(row.actual_amount),
            "currency": row.currency,
            "status": row.status,
            "workflow_instance_id": row.workflow_instance_id,
            "journal_id": row.journal_id,
        }
