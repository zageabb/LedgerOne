from __future__ import annotations

from ledgerone.module_registry import module_registry
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.services.context import AccessContext


def workflow_submission_context(context: AccessContext, domain_permission: str) -> AccessContext:
    """Return a context that can create workflow state after proving domain authority.

    This adds only `workflows.write` for the internal call to WorkflowService.start. It
    does not grant review, approval, posting, or any additional accounting/business right.
    Generic API callers still need `workflows.write` themselves.
    """
    if not context.can(domain_permission):
        raise PermissionError(domain_permission)
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


def required_post_permission(instance: WorkflowInstance) -> str | None:
    manifest = module_registry.workflow_manifest(instance.entity_type)
    return manifest.workflow_post_permission if manifest else None


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
