from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow
from ledgerone.models.ledger import Journal
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.control_accounts import validate_control_account_lines
from ledgerone.services.currency import organisation_base_currency, validate_journal_lines
from ledgerone.services.ledger import LedgerService


class JournalWorkflowService:
    """Route manual/AI journal proposals through the common User Actions workflow.

    The pending journal is stored inside the workflow instance metadata. Nothing is
    written to the ledger until an authorised user completes any required workflow
    steps and explicitly executes the Post action.
    """

    ENTITY_TYPE = "journal"

    @staticmethod
    def _serialise_lines(context: AccessContext, lines: list[dict]) -> tuple[list[dict], Decimal]:
        raw_lines = [dict(row or {}) for row in (lines or [])]
        # Run the same accounting-shape, base-currency and control-account checks as a
        # normal manual journal before asking somebody to review an impossible request.
        validate_journal_lines(context, raw_lines)
        validate_control_account_lines(context, raw_lines, source_module="ledger")
        prepared, total_debit, _ = LedgerService._prepare_lines(context, raw_lines)

        serialised = []
        for _, account, debit, credit, raw in prepared:
            serialised.append(
                {
                    "account_id": account.id,
                    "account_code": account.code,
                    "account_name": account.name,
                    "description": raw.get("description"),
                    "debit": str(debit),
                    "credit": str(credit),
                    "currency": raw.get("currency"),
                    "dimensions": raw.get("dimensions") or {},
                }
            )
        return serialised, total_debit

    @staticmethod
    def _workflow_submission_context(context: AccessContext) -> AccessContext:
        """Permit a domain-authorised caller to create its controlled workflow record.

        `workflows.write` remains required for the generic workflow API. Domain adapters
        such as journal submission instead prove their own business permission first and
        receive only the internal workflow-create capability needed to route the work.
        This does not grant review, approval, posting, or any additional accounting right.
        """
        if context.can("workflows.write"):
            return context
        return AccessContext(
            identity_type=context.identity_type,
            organisation_id=context.organisation_id,
            user_id=context.user_id,
            api_key_id=context.api_key_id,
            full_access=context.full_access,
            permissions=frozenset(set(context.permissions) | {"workflows.write"}),
        )

    @staticmethod
    def create_request(
        context: AccessContext,
        *,
        journal_date: date,
        description: str,
        lines: list[dict],
        reference: str | None = None,
        source_module: str = "ledger",
        source_reference: str | None = None,
        metadata: dict | None = None,
        workflow_definition_id: str | None = None,
    ) -> WorkflowInstance:
        if not context.can("ledger.journals.post"):
            raise PermissionError("ledger.journals.post")
        if not context.organisation_id:
            raise WorkflowError("An organisation is required")

        clean_description = (description or "").strip() or "Manual journal"
        clean_reference = (reference or "").strip() or None
        # Reject a request that could not be posted today before it enters somebody's
        # review queue. The same period guard is run again at final Post time.
        LedgerService.assert_posting_date_open(context, journal_date)
        # Validate the accounting request before creating any workflow state. This also
        # preserves the existing error contract for unsupported currency/control entries.
        serialised_lines, total = JournalWorkflowService._serialise_lines(context, lines)
        request_id = new_id()
        base_currency = organisation_base_currency(context)
        request_metadata = dict(metadata or {})
        request_metadata.update(
            {
                "create_post_action": True,
                "journal_request": {
                    "journal_date": journal_date.isoformat(),
                    "description": clean_description,
                    "reference": clean_reference,
                    "lines": serialised_lines,
                    "source_module": (source_module or "ledger").strip() or "ledger",
                    "source_reference": source_reference,
                },
            }
        )

        workflow = WorkflowService.start(
            JournalWorkflowService._workflow_submission_context(context),
            entity_type=JournalWorkflowService.ENTITY_TYPE,
            entity_id=request_id,
            title=clean_description,
            amount=total,
            currency=base_currency,
            source_module=(source_module or "ledger").strip() or "ledger",
            metadata=request_metadata,
            definition_id=workflow_definition_id,
            originator_user_id=context.user_id,
            create_post_action=True,
            commit=False,
        )
        record_audit_event(
            context,
            module_id="ledger",
            action="journal_workflow_submitted",
            entity_type="journal_request",
            entity_id=request_id,
            detail={
                "workflow_instance_id": workflow.id,
                "journal_date": journal_date.isoformat(),
                "reference": clean_reference,
                "total": str(total),
                "line_count": len(serialised_lines),
                "source_module": source_module,
                "status": workflow.status,
            },
        )
        db.session.commit()
        return workflow

    @staticmethod
    def request_payload(instance: WorkflowInstance) -> dict:
        return dict((instance.metadata_json or {}).get("journal_request") or {})

    @staticmethod
    def post_from_action(context: AccessContext, action_id: str) -> Journal:
        if not context.can("workflows.post"):
            raise PermissionError("workflows.post")
        if not context.can("ledger.journals.post"):
            raise PermissionError("ledger.journals.post")

        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open posting action not found")
        if action.action_type != "post":
            raise WorkflowError("This user action is not a posting action")
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")

        instance = action.workflow_instance
        if instance.entity_type != JournalWorkflowService.ENTITY_TYPE or instance.status != "ready_to_post":
            raise WorkflowError("Journal workflow is not ready for posting")
        payload = JournalWorkflowService.request_payload(instance)
        if not payload:
            raise WorkflowError("Journal workflow payload is missing")
        if (instance.metadata_json or {}).get("posted_journal_id"):
            raise WorkflowError("Journal workflow has already been posted")

        lines = []
        for row in payload.get("lines") or []:
            lines.append(
                {
                    "account_id": row.get("account_id"),
                    "description": row.get("description"),
                    "debit": row.get("debit") or 0,
                    "credit": row.get("credit") or 0,
                    "currency": row.get("currency"),
                    "dimensions": row.get("dimensions") or {},
                }
            )

        effective_date = date.fromisoformat(payload["journal_date"])
        journal = LedgerService.post_journal(
            context,
            journal_date=effective_date,
            description=payload.get("description") or instance.title,
            reference=payload.get("reference"),
            lines=lines,
            source_module=payload.get("source_module") or instance.source_module or "ledger",
            source_reference=payload.get("source_reference") or instance.entity_id,
            metadata={
                "workflow_instance_id": instance.id,
                "journal_request_id": instance.entity_id,
                "workflow_originator_user_id": instance.originator_user_id,
            },
            commit=False,
        )

        instance.status = "posted"
        instance.completed_at = utcnow()
        instance.metadata_json = {
            **(instance.metadata_json or {}),
            "posted_journal_id": journal.id,
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
            module_id="ledger",
            action="journal_workflow_posted",
            entity_type="journal_request",
            entity_id=instance.entity_id,
            detail={
                "workflow_instance_id": instance.id,
                "journal_id": journal.id,
                "journal_date": effective_date.isoformat(),
                "reference": journal.reference,
                "total": str(instance.amount) if instance.amount is not None else None,
                "source_module": journal.source_module,
            },
        )
        db.session.commit()
        return journal
