"""Independently verified, company-scoped approval for direct trading postings.

An arbitrary metadata dictionary is never sufficient evidence of approval.
Only the controlled workflow posting adapter passes approved_workflow_id.
"""
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import Setting
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.services.approval_policy import ApprovalPolicyService


def require_trading_approval(context, *, policy_key: str, approved_workflow_id: str | None,
                             fields: dict, total: Decimal) -> None:
    if policy_key not in {"sales_invoice", "purchase_bill"}:
        raise ValueError("Unsupported trading approval policy")

    configured = ApprovalPolicyService.get(context, policy_key)
    domain_required = ApprovalPolicyService._applies(configured, total)
    global_setting = Setting.query.filter_by(
        organisation_id=context.organisation_id, scope="approval_controls", key="threshold"
    ).first()
    global_policy = dict(global_setting.value or {}) if global_setting else {}
    threshold = ApprovalPolicyService._money(global_policy.get("threshold"))
    global_required = bool(global_policy.get("enabled") and threshold is not None and total >= threshold)
    if not domain_required and not global_required:
        return

    instance = db.session.get(WorkflowInstance, approved_workflow_id) if approved_workflow_id else None
    if (not instance or instance.organisation_id != context.organisation_id
            or instance.entity_type != policy_key or instance.status != "ready_to_post"
            or not instance.originator_user_id or instance.amount != total):
        raise ValueError("Independent approval required: submit this transaction through its approval workflow")

    snapshot = (instance.metadata_json or {}).get(policy_key + "_request")
    if not isinstance(snapshot, dict):
        raise ValueError("Approved transaction snapshot is unavailable")
    for key, value in fields.items():
        if snapshot.get(key) != value:
            raise ValueError("Transaction content differs from its approved workflow")

    approvals = UserAction.query.filter_by(
        workflow_instance_id=instance.id, action_type="approve",
        status="completed", decision="approve"
    ).all()
    if not any(a.completed_by_user_id and a.completed_by_user_id != instance.originator_user_id
               for a in approvals):
        raise ValueError("An independent checker must approve before posting")
