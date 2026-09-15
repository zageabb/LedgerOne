from __future__ import annotations

from datetime import date

from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow
from ledgerone.modules.expense_claims.models import ExpenseClaim
from ledgerone.modules.expense_claims.services import ExpenseClaimService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.posting import workflow_submission_context
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class ExpenseClaimWorkflowService:
    """Route submitted expense claims through the common User Actions workflow."""

    ENTITY_TYPE = "expense_claim"

    @staticmethod
    def _claim(context: AccessContext, claim_id: str) -> ExpenseClaim:
        claim = db.session.get(ExpenseClaim, claim_id)
        if not claim or claim.organisation_id != context.organisation_id:
            raise WorkflowError("Expense claim not found")
        return claim

    @staticmethod
    def _snapshot(claim: ExpenseClaim) -> dict:
        return {
            "claim_id": claim.id,
            "claim_number": claim.claim_number,
            "claimant_name": claim.claimant_name,
            "claim_date": claim.claim_date.isoformat(),
            "currency": claim.currency,
            "subtotal": str(claim.subtotal),
            "tax_total": str(claim.tax_total),
            "total": str(claim.total),
            "reimbursement_account_id": claim.reimbursement_account_id,
            "lines": [
                {
                    "line_number": line.line_number,
                    "expense_date": line.expense_date.isoformat(),
                    "merchant": line.merchant,
                    "description": line.description,
                    "net_amount": str(line.net_amount),
                    "tax_amount": str(line.tax_amount),
                    "tax_code_id": line.tax_code_id,
                    "expense_account_id": line.expense_account_id,
                    "expense_account_code": line.expense_account.code if line.expense_account else None,
                    "expense_account_name": line.expense_account.name if line.expense_account else None,
                }
                for line in claim.lines
            ],
        }

    @staticmethod
    def submit_request(
        context: AccessContext,
        claim_id: str,
        *,
        workflow_definition_id: str | None = None,
    ) -> WorkflowInstance:
        submission_context = workflow_submission_context(context, "expense_claims.write")
        claim = ExpenseClaimWorkflowService._claim(context, claim_id)
        if claim.status != "draft":
            raise WorkflowError("Only a draft expense claim can be submitted")

        # Submit/recalculate first but keep the domain row and workflow creation in the
        # same transaction. A failure below therefore leaves the claim as a draft.
        try:
            claim = ExpenseClaimService.submit(context, claim.id, commit=False)
            snapshot = ExpenseClaimWorkflowService._snapshot(claim)
            workflow = WorkflowService.start(
                submission_context,
                entity_type=ExpenseClaimWorkflowService.ENTITY_TYPE,
                entity_id=f"{claim.id}:{new_id()}",
                title=f"Expense claim {claim.claim_number} - {claim.claimant_name}",
                amount=claim.total,
                currency=claim.currency,
                source_module="expense_claims",
                metadata={
                    "create_post_action": True,
                    "expense_claim_id": claim.id,
                    "expense_claim_snapshot": snapshot,
                },
                definition_id=workflow_definition_id,
                originator_user_id=claim.claimant_user_id or context.user_id,
                create_post_action=True,
                commit=False,
            )
            claim.metadata_json = {
                **(claim.metadata_json or {}),
                "workflow_instance_id": workflow.id,
            }
            record_audit_event(
                context,
                module_id="expense_claims",
                action="expense_claim_workflow_submitted",
                entity_type="expense_claim",
                entity_id=claim.id,
                detail={
                    "workflow_instance_id": workflow.id,
                    "claim_number": claim.claim_number,
                    "total": str(claim.total),
                    "status": workflow.status,
                },
            )
            db.session.commit()
            return workflow
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def complete_action(
        context: AccessContext,
        action_id: str,
        *,
        decision: str,
        comments: str | None = None,
    ) -> WorkflowInstance:
        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open user action not found")
        instance = action.workflow_instance
        if instance.entity_type != ExpenseClaimWorkflowService.ENTITY_TYPE:
            raise WorkflowError("Action does not belong to an expense claim workflow")
        claim_id = (instance.metadata_json or {}).get("expense_claim_id")
        claim = ExpenseClaimWorkflowService._claim(context, claim_id)
        clean_decision = (decision or "approve").strip().lower()
        if clean_decision not in {"approve", "reject", "return"}:
            raise WorkflowError("Decision must be approve, reject or return")

        # Approval can use the common engine unchanged: the claim remains frozen in
        # submitted state while the workflow advances to its next step/ready-to-post.
        if clean_decision == "approve":
            return WorkflowService.complete_action(
                context,
                action_id,
                decision=clean_decision,
                comments=comments,
            )

        # Reject/return have domain consequences, so complete both the workflow action
        # and the expense-claim status in one database transaction.
        permission = "workflows.post" if action.action_type == "post" else (
            "workflows.approve" if action.action_type == "approve" else "workflows.review"
        )
        if not context.can(permission):
            raise PermissionError(permission)
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")

        try:
            action.status = "completed"
            action.decision = clean_decision
            action.comments = (comments or "").strip() or None
            action.completed_by_user_id = context.user_id
            action.completed_at = utcnow()

            if clean_decision == "reject":
                instance.status = "rejected"
                instance.completed_at = utcnow()
                claim.status = "rejected"
                claim.metadata_json = {
                    **(claim.metadata_json or {}),
                    "rejection_reason": action.comments,
                    "workflow_instance_id": instance.id,
                }
                domain_action = "claim_rejected"
            else:
                instance.status = "returned"
                instance.completed_at = utcnow()
                claim.status = "draft"
                claim.metadata_json = {
                    **(claim.metadata_json or {}),
                    "returned_from_workflow_id": instance.id,
                    "return_reason": action.comments,
                }
                # Any other outstanding step belongs to the frozen submission and must
                # not survive after the claim is reopened for editing.
                for other in instance.actions:
                    if other.id != action.id and other.status == "open":
                        other.status = "cancelled"
                domain_action = "claim_returned_to_draft"

            record_audit_event(
                context,
                module_id="workflows",
                action="user_action_completed",
                entity_type="user_action",
                entity_id=action.id,
                detail={
                    "workflow_instance_id": instance.id,
                    "action_type": action.action_type,
                    "decision": clean_decision,
                    "comments": action.comments,
                    "resulting_status": instance.status,
                },
            )
            record_audit_event(
                context,
                module_id="expense_claims",
                action=domain_action,
                entity_type="expense_claim",
                entity_id=claim.id,
                detail={"reason": action.comments, "workflow_instance_id": instance.id},
            )
            db.session.commit()
            return instance
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def post_from_action(
        context: AccessContext,
        action_id: str,
        *,
        posting_date: date,
    ) -> ExpenseClaim:
        if not context.can("workflows.post"):
            raise PermissionError("workflows.post")
        if not context.can("expense_claims.approve"):
            raise PermissionError("expense_claims.approve")

        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open posting action not found")
        if action.action_type != "post":
            raise WorkflowError("This user action is not a posting action")
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")

        instance = action.workflow_instance
        if instance.entity_type != ExpenseClaimWorkflowService.ENTITY_TYPE or instance.status != "ready_to_post":
            raise WorkflowError("Expense claim workflow is not ready for posting")
        claim_id = (instance.metadata_json or {}).get("expense_claim_id")
        claim = ExpenseClaimWorkflowService._claim(context, claim_id)
        if claim.status != "submitted":
            raise WorkflowError("Expense claim is no longer in submitted state")
        if (instance.metadata_json or {}).get("posted_expense_claim_id"):
            raise WorkflowError("Expense claim workflow has already been posted")

        # Detect any unexpected data mutation after review. Returned claims are editable,
        # but a submitted claim must match the exact snapshot that reviewers saw.
        current_snapshot = ExpenseClaimWorkflowService._snapshot(claim)
        reviewed_snapshot = (instance.metadata_json or {}).get("expense_claim_snapshot") or {}
        if current_snapshot != reviewed_snapshot:
            raise WorkflowError("Expense claim changed after submission; return it to draft and review it again")

        try:
            claim, journal = ExpenseClaimService.approve_and_post(
                context,
                claim.id,
                posting_date=posting_date,
                commit=False,
            )
            instance.status = "posted"
            instance.completed_at = utcnow()
            instance.metadata_json = {
                **(instance.metadata_json or {}),
                "posted_expense_claim_id": claim.id,
                "posted_journal_id": journal.id,
            }
            action.status = "completed"
            action.decision = "posted"
            action.completed_by_user_id = context.user_id
            action.completed_at = utcnow()
            for other in instance.actions:
                if other.id != action.id and other.status == "open":
                    other.status = "cancelled"
            claim.metadata_json = {
                **(claim.metadata_json or {}),
                "workflow_instance_id": instance.id,
            }
            record_audit_event(
                context,
                module_id="expense_claims",
                action="expense_claim_workflow_posted",
                entity_type="expense_claim",
                entity_id=claim.id,
                detail={
                    "workflow_instance_id": instance.id,
                    "journal_id": journal.id,
                    "posting_date": posting_date.isoformat(),
                    "total": str(claim.total),
                },
            )
            db.session.commit()
            return claim
        except Exception:
            db.session.rollback()
            raise
