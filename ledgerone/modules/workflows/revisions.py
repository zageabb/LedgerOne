from __future__ import annotations

from datetime import date

from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.posting import workflow_submission_context
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.currency import organisation_base_currency
from ledgerone.services.ledger import LedgerService


class WorkflowRevisionService:
    """Replace returned payload-backed proposals with fully re-reviewed workflows.

    Returned workflow instances remain immutable history. A correction creates a new
    workflow entity id, re-runs current validation and workflow-rule selection, and links
    the old/new instances through metadata. This prevents revised values from inheriting
    an approval path that may no longer be appropriate.
    """

    @staticmethod
    def _returned_action(
        context: AccessContext,
        action_id: str,
        *,
        entity_type: str,
        domain_permission: str,
    ) -> tuple[UserAction, WorkflowInstance]:
        if not context.can(domain_permission):
            raise PermissionError(domain_permission)
        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open returned-workflow action not found")
        if action.action_type != "review":
            raise WorkflowError("Only the returned correction action can be resubmitted")
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")
        instance = action.workflow_instance
        if instance.entity_type != entity_type or instance.status != "returned":
            raise WorkflowError("Workflow is not awaiting correction")
        return action, instance

    @staticmethod
    def _replacement(
        context: AccessContext,
        action: UserAction,
        old: WorkflowInstance,
        *,
        domain_permission: str,
        title: str,
        amount,
        currency: str,
        metadata: dict,
        revision_source_module: str,
    ) -> WorkflowInstance:
        new_metadata = dict(metadata or {})
        new_metadata.update(
            {
                "create_post_action": True,
                "replaces_workflow_instance_id": old.id,
                "revision_source_module": revision_source_module,
            }
        )
        replacement = WorkflowService.start(
            workflow_submission_context(context, domain_permission),
            entity_type=old.entity_type,
            entity_id=new_id(),
            title=title,
            amount=amount,
            currency=currency,
            source_module=old.source_module,
            metadata=new_metadata,
            # Deliberately resolve the workflow again. Revised amount/coding may require
            # a stronger rule than the returned proposal originally matched.
            definition_id=None,
            originator_user_id=context.user_id,
            create_post_action=True,
            commit=False,
        )

        old.status = "superseded"
        old.completed_at = utcnow()
        old.metadata_json = {
            **(old.metadata_json or {}),
            "replaced_by_workflow_instance_id": replacement.id,
        }
        action.status = "completed"
        action.decision = "resubmitted"
        action.completed_by_user_id = context.user_id
        action.completed_at = utcnow()
        for other in old.actions:
            if other.id != action.id and other.status == "open":
                other.status = "cancelled"

        record_audit_event(
            context,
            module_id="workflows",
            action="workflow_replaced_after_return",
            entity_type=old.entity_type,
            entity_id=old.entity_id,
            detail={
                "old_workflow_instance_id": old.id,
                "replacement_workflow_instance_id": replacement.id,
                "old_amount": str(old.amount) if old.amount is not None else None,
                "replacement_amount": str(replacement.amount) if replacement.amount is not None else None,
                "revision_source_module": revision_source_module,
            },
        )
        db.session.flush()
        return replacement

    @staticmethod
    def _value(changes: dict, key: str, fallback):
        return changes[key] if key in changes and changes[key] is not None else fallback

    @staticmethod
    def _date(changes: dict, key: str, fallback: str | None) -> date | None:
        value = WorkflowRevisionService._value(changes, key, fallback)
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    @staticmethod
    def revise_sales_invoice(
        context: AccessContext,
        action_id: str,
        changes: dict,
        *,
        revision_source_module: str,
    ) -> WorkflowInstance:
        from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService

        action, old = WorkflowRevisionService._returned_action(
            context,
            action_id,
            entity_type=SalesInvoiceWorkflowService.ENTITY_TYPE,
            domain_permission="sales.write",
        )
        old_payload = SalesInvoiceWorkflowService.request_payload(old)
        if not old_payload:
            raise WorkflowError("Returned sales invoice payload is missing")
        original_metadata = dict(old.metadata_json or {})
        try:
            # Release only this returned proposal's number while the validator checks the
            # revised request. The historical metadata is restored before commit.
            temp_metadata = dict(original_metadata)
            temp_payload = dict(old_payload)
            temp_payload["invoice_number"] = f"__superseded__{old.id}"
            temp_metadata["sales_invoice_request"] = temp_payload
            old.metadata_json = temp_metadata
            db.session.flush()

            payload, total = SalesInvoiceWorkflowService._validate_request(
                context,
                customer_id=str(WorkflowRevisionService._value(changes, "customer_id", old_payload["customer_id"])),
                invoice_number=str(WorkflowRevisionService._value(changes, "invoice_number", old_payload["invoice_number"])),
                invoice_date=WorkflowRevisionService._date(changes, "invoice_date", old_payload["invoice_date"]),
                due_date=WorkflowRevisionService._date(changes, "due_date", old_payload.get("due_date")),
                description=str(WorkflowRevisionService._value(changes, "description", old_payload.get("description") or "Sales")),
                amount=WorkflowRevisionService._value(changes, "amount", old_payload["amount"]),
                receivable_account_id=str(WorkflowRevisionService._value(changes, "receivable_account_id", old_payload["receivable_account_id"])),
                revenue_account_id=str(WorkflowRevisionService._value(changes, "revenue_account_id", old_payload["revenue_account_id"])),
                currency=str(WorkflowRevisionService._value(changes, "currency", old_payload["currency"])),
                tax_code_id=WorkflowRevisionService._value(changes, "tax_code_id", old_payload.get("tax_code_id")),
            )
            old.metadata_json = original_metadata
            replacement = WorkflowRevisionService._replacement(
                context,
                action,
                old,
                domain_permission="sales.write",
                title=f"Invoice {payload['invoice_number']} - {payload['customer_name']}",
                amount=total,
                currency=payload["currency"],
                metadata={
                    "proposal_source_module": original_metadata.get("proposal_source_module") or old.source_module,
                    "source_reference": original_metadata.get("source_reference"),
                    "sales_invoice_request": payload,
                },
                revision_source_module=revision_source_module,
            )
            record_audit_event(
                context,
                module_id="sales",
                action="sales_invoice_workflow_resubmitted",
                entity_type="sales_invoice_request",
                entity_id=replacement.entity_id,
                detail={
                    "old_workflow_instance_id": old.id,
                    "workflow_instance_id": replacement.id,
                    "invoice_number": payload["invoice_number"],
                    "total": payload["total"],
                },
            )
            db.session.commit()
            return replacement
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def revise_purchase_bill(
        context: AccessContext,
        action_id: str,
        changes: dict,
        *,
        revision_source_module: str,
    ) -> WorkflowInstance:
        from ledgerone.modules.workflows.purchase_bill_requests import PurchaseBillWorkflowService

        action, old = WorkflowRevisionService._returned_action(
            context,
            action_id,
            entity_type=PurchaseBillWorkflowService.ENTITY_TYPE,
            domain_permission="purchases.write",
        )
        old_payload = PurchaseBillWorkflowService.request_payload(old)
        if not old_payload:
            raise WorkflowError("Returned purchase bill payload is missing")
        original_metadata = dict(old.metadata_json or {})
        try:
            temp_metadata = dict(original_metadata)
            temp_payload = dict(old_payload)
            temp_payload["bill_number"] = f"__superseded__{old.id}"
            temp_metadata["purchase_bill_request"] = temp_payload
            old.metadata_json = temp_metadata
            db.session.flush()

            payload, total = PurchaseBillWorkflowService._validate_request(
                context,
                supplier_id=str(WorkflowRevisionService._value(changes, "supplier_id", old_payload["supplier_id"])),
                bill_number=str(WorkflowRevisionService._value(changes, "bill_number", old_payload["bill_number"])),
                bill_date=WorkflowRevisionService._date(changes, "bill_date", old_payload["bill_date"]),
                due_date=WorkflowRevisionService._date(changes, "due_date", old_payload.get("due_date")),
                description=str(WorkflowRevisionService._value(changes, "description", old_payload.get("description") or "Purchase")),
                amount=WorkflowRevisionService._value(changes, "amount", old_payload["amount"]),
                payable_account_id=str(WorkflowRevisionService._value(changes, "payable_account_id", old_payload["payable_account_id"])),
                expense_account_id=str(WorkflowRevisionService._value(changes, "expense_account_id", old_payload["expense_account_id"])),
                currency=str(WorkflowRevisionService._value(changes, "currency", old_payload["currency"])),
                tax_code_id=WorkflowRevisionService._value(changes, "tax_code_id", old_payload.get("tax_code_id")),
            )
            old.metadata_json = original_metadata
            replacement = WorkflowRevisionService._replacement(
                context,
                action,
                old,
                domain_permission="purchases.write",
                title=f"Bill {payload['bill_number']} - {payload['supplier_name']}",
                amount=total,
                currency=payload["currency"],
                metadata={
                    "proposal_source_module": original_metadata.get("proposal_source_module") or old.source_module,
                    "source_reference": original_metadata.get("source_reference"),
                    "purchase_bill_request": payload,
                },
                revision_source_module=revision_source_module,
            )
            record_audit_event(
                context,
                module_id="purchases",
                action="purchase_bill_workflow_resubmitted",
                entity_type="purchase_bill_request",
                entity_id=replacement.entity_id,
                detail={
                    "old_workflow_instance_id": old.id,
                    "workflow_instance_id": replacement.id,
                    "bill_number": payload["bill_number"],
                    "total": payload["total"],
                },
            )
            db.session.commit()
            return replacement
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def revise_journal(
        context: AccessContext,
        action_id: str,
        changes: dict,
        *,
        revision_source_module: str,
    ) -> WorkflowInstance:
        from ledgerone.modules.workflows.journal_requests import JournalWorkflowService

        action, old = WorkflowRevisionService._returned_action(
            context,
            action_id,
            entity_type=JournalWorkflowService.ENTITY_TYPE,
            domain_permission="ledger.journals.post",
        )
        old_payload = JournalWorkflowService.request_payload(old)
        if not old_payload:
            raise WorkflowError("Returned journal payload is missing")
        try:
            journal_date = WorkflowRevisionService._date(changes, "journal_date", old_payload["journal_date"])
            LedgerService.assert_posting_date_open(context, journal_date)
            raw_lines = WorkflowRevisionService._value(changes, "lines", None)
            if raw_lines is None:
                raw_lines = [
                    {
                        "account_id": row.get("account_id"),
                        "description": row.get("description"),
                        "debit": row.get("debit") or 0,
                        "credit": row.get("credit") or 0,
                        "currency": row.get("currency"),
                        "dimensions": row.get("dimensions") or {},
                    }
                    for row in old_payload.get("lines") or []
                ]
            serialised_lines, total = JournalWorkflowService._serialise_lines(context, raw_lines)
            description = str(WorkflowRevisionService._value(changes, "description", old_payload.get("description") or "Manual journal")).strip() or "Manual journal"
            reference = WorkflowRevisionService._value(changes, "reference", old_payload.get("reference"))
            reference = str(reference).strip() if reference not in (None, "") else None
            base_currency = organisation_base_currency(context)
            payload = {
                "journal_date": journal_date.isoformat(),
                "description": description,
                "reference": reference,
                "lines": serialised_lines,
                "source_module": old_payload.get("source_module") or old.source_module or "ledger",
                "source_reference": old_payload.get("source_reference"),
            }
            replacement = WorkflowRevisionService._replacement(
                context,
                action,
                old,
                domain_permission="ledger.journals.post",
                title=description,
                amount=total,
                currency=base_currency,
                metadata={"journal_request": payload},
                revision_source_module=revision_source_module,
            )
            record_audit_event(
                context,
                module_id="ledger",
                action="journal_workflow_resubmitted",
                entity_type="journal_request",
                entity_id=replacement.entity_id,
                detail={
                    "old_workflow_instance_id": old.id,
                    "workflow_instance_id": replacement.id,
                    "journal_date": payload["journal_date"],
                    "reference": payload["reference"],
                    "total": str(total),
                    "line_count": len(serialised_lines),
                },
            )
            db.session.commit()
            return replacement
        except Exception:
            db.session.rollback()
            raise
