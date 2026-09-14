from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.services.context import AccessContext


def record_audit_event(
    context: AccessContext,
    *,
    module_id: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
):
    """Queue an audit event in the caller's current transaction.

    The caller owns the commit/rollback boundary so business data and its audit event
    succeed or fail together.
    """
    event = AuditEvent(
        organisation_id=context.organisation_id,
        actor_type=context.identity_type,
        actor_id=context.user_id or context.api_key_id,
        module_id=module_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
    )
    db.session.add(event)
    return event
