from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import new_id, utcnow
from ledgerone.services.audit_integrity import (
    CHAIN_VERSION,
    audit_scope,
    calculate_event_hash,
    lock_chain_head,
)
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
    """Queue an append-only, hash-chained audit event in the current transaction.

    Business data, its audit event and the chain-head advance share the caller's
    commit/rollback boundary. A rolled-back business transaction therefore cannot
    leave an orphan audit record or advance the retained chain head.
    """
    created_at = utcnow()
    event_id = new_id()
    scope = audit_scope(context.organisation_id)
    head = lock_chain_head(context.organisation_id)
    sequence = int(head.last_sequence or 0) + 1
    previous_hash = head.last_hash
    clean_detail = detail or {}

    event_hash = calculate_event_hash(
        event_id=event_id,
        organisation_id=context.organisation_id,
        actor_type=context.identity_type,
        actor_id=context.user_id or context.api_key_id,
        module_id=module_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=clean_detail,
        created_at=created_at,
        chain_scope=scope,
        chain_sequence=sequence,
        previous_hash=previous_hash,
        chain_version=CHAIN_VERSION,
    )
    audit_event = AuditEvent(
        id=event_id,
        organisation_id=context.organisation_id,
        actor_type=context.identity_type,
        actor_id=context.user_id or context.api_key_id,
        module_id=module_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=clean_detail,
        created_at=created_at,
        chain_scope=scope,
        chain_sequence=sequence,
        previous_hash=previous_hash,
        event_hash=event_hash,
        chain_version=CHAIN_VERSION,
    )
    head.last_sequence = sequence
    head.last_hash = event_hash
    head.updated_at = created_at
    db.session.add(audit_event)
    return audit_event
