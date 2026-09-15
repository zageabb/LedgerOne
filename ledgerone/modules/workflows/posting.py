from __future__ import annotations

from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.services.context import AccessContext


# Final posting remains domain-authorised. A purchasing user should not need arbitrary
# manual-journal rights merely because Purchases ultimately writes through LedgerService.
POST_PERMISSIONS = {
    "scheduled_transaction": "ledger.journals.post",
    "journal": "ledger.journals.post",
    "purchase_bill": "purchases.write",
    "sales_invoice": "sales.write",
    "expense_claim": "expense_claims.approve",
}


def required_post_permission(instance: WorkflowInstance) -> str | None:
    return POST_PERMISSIONS.get(instance.entity_type)


def can_post_instance(context: AccessContext, instance: WorkflowInstance) -> bool:
    if not context.can("workflows.post"):
        return False
    permission = required_post_permission(instance)
    return bool(permission and context.can(permission))


def can_post_action(context: AccessContext, action: UserAction) -> bool:
    return bool(
        action
        and action.action_type == "post"
        and action.status == "open"
        and can_post_instance(context, action.workflow_instance)
    )
