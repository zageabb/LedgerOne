from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session

from ledgerone.extensions import db
from ledgerone.models.audit import AuditChainHead, AuditEvent
from ledgerone.models.core import Organisation, new_id, utcnow
from ledgerone.services.context import AccessContext


CHAIN_VERSION = 1
GLOBAL_SCOPE = "__GLOBAL__"


class AuditImmutableError(RuntimeError):
    """Raised when persisted audit evidence is changed through the ORM."""


def audit_scope(organisation_id: str | None) -> str:
    return organisation_id or GLOBAL_SCOPE


def _normalise_datetime(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return str(value)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def _json_default(value):
    if isinstance(value, datetime):
        return _normalise_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def canonical_event_payload(
    *,
    event_id: str,
    organisation_id: str | None,
    actor_type: str,
    actor_id: str | None,
    module_id: str,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    detail: dict | None,
    created_at,
    chain_scope: str,
    chain_sequence: int,
    previous_hash: str | None,
    chain_version: int = CHAIN_VERSION,
) -> str:
    payload = {
        "action": action,
        "actor_id": actor_id or "",
        "actor_type": actor_type,
        "chain_scope": chain_scope,
        "chain_sequence": int(chain_sequence),
        "chain_version": int(chain_version),
        "created_at": _normalise_datetime(created_at),
        "detail": detail or {},
        "entity_id": entity_id or "",
        "entity_type": entity_type or "",
        "event_id": event_id,
        "module_id": module_id,
        "organisation_id": organisation_id or "",
        "previous_hash": previous_hash or "",
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def calculate_event_hash(**values) -> str:
    payload = canonical_event_payload(**values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def calculate_row_hash(row: AuditEvent) -> str:
    return calculate_event_hash(
        event_id=row.id,
        organisation_id=row.organisation_id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        module_id=row.module_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        detail=row.detail or {},
        created_at=row.created_at,
        chain_scope=row.chain_scope,
        chain_sequence=row.chain_sequence,
        previous_hash=row.previous_hash,
        chain_version=row.chain_version,
    )


def lock_chain_head(
    organisation_id: str | None,
    *,
    session: Session | None = None,
) -> AuditChainHead:
    scope = audit_scope(organisation_id)
    session = session or db.session

    for candidate in session.new:
        if isinstance(candidate, AuditChainHead) and candidate.scope_key == scope:
            return candidate

    head = (
        session.query(AuditChainHead)
        .filter(AuditChainHead.scope_key == scope)
        .with_for_update()
        .one_or_none()
    )
    if head is None:
        head = AuditChainHead(
            scope_key=scope,
            organisation_id=organisation_id,
            last_sequence=0,
            last_hash=None,
            updated_at=utcnow(),
        )
        session.add(head)
    return head


class AuditIntegrityService:
    @staticmethod
    def verify(context: AccessContext) -> dict:
        if not context.can("audit.read"):
            raise PermissionError("audit.read")
        if not context.organisation_id:
            raise ValueError("An organisation is required")

        scope = audit_scope(context.organisation_id)
        head = db.session.get(AuditChainHead, scope)
        rows = (
            AuditEvent.query.filter_by(
                organisation_id=context.organisation_id,
                chain_scope=scope,
            )
            .order_by(AuditEvent.chain_sequence.asc())
            .all()
        )

        expected_sequence = 1
        previous_hash = None
        for row in rows:
            if row.chain_sequence != expected_sequence:
                return {
                    "valid": False,
                    "checked_events": expected_sequence - 1,
                    "first_error": "sequence_gap",
                    "event_id": row.id,
                    "expected_sequence": expected_sequence,
                    "actual_sequence": row.chain_sequence,
                }
            if row.previous_hash != previous_hash:
                return {
                    "valid": False,
                    "checked_events": expected_sequence - 1,
                    "first_error": "previous_hash_mismatch",
                    "event_id": row.id,
                    "expected_previous_hash": previous_hash,
                    "actual_previous_hash": row.previous_hash,
                }
            calculated = calculate_row_hash(row)
            if calculated != row.event_hash:
                return {
                    "valid": False,
                    "checked_events": expected_sequence - 1,
                    "first_error": "event_hash_mismatch",
                    "event_id": row.id,
                    "expected_hash": calculated,
                    "actual_hash": row.event_hash,
                }
            previous_hash = row.event_hash
            expected_sequence += 1

        last_sequence = len(rows)
        if head is None:
            if rows:
                return {
                    "valid": False,
                    "checked_events": len(rows),
                    "first_error": "missing_chain_head",
                }
            return {
                "valid": True,
                "checked_events": 0,
                "last_sequence": 0,
                "last_hash": None,
            }

        if head.last_sequence != last_sequence or head.last_hash != previous_hash:
            return {
                "valid": False,
                "checked_events": len(rows),
                "first_error": "chain_head_mismatch",
                "expected_last_sequence": last_sequence,
                "actual_last_sequence": head.last_sequence,
                "expected_last_hash": previous_hash,
                "actual_last_hash": head.last_hash,
            }

        return {
            "valid": True,
            "checked_events": len(rows),
            "last_sequence": head.last_sequence,
            "last_hash": head.last_hash,
            "chain_version": CHAIN_VERSION,
        }


_guard_installed = False


def _chain_new_event(session: Session, obj: AuditEvent) -> None:
    # Most code uses record_audit_event(), which assigns chain metadata immediately.
    # This fallback protects legacy/internal direct AuditEvent constructors so every
    # inserted row still enters the same chain at the persistence boundary.
    if obj.chain_scope and obj.chain_sequence and obj.event_hash:
        return

    if not obj.id:
        obj.id = new_id()
    if not obj.created_at:
        obj.created_at = utcnow()

    scope = audit_scope(obj.organisation_id)
    head = lock_chain_head(obj.organisation_id, session=session)
    sequence = int(head.last_sequence or 0) + 1
    previous_hash = head.last_hash
    digest = calculate_event_hash(
        event_id=obj.id,
        organisation_id=obj.organisation_id,
        actor_type=obj.actor_type,
        actor_id=obj.actor_id,
        module_id=obj.module_id,
        action=obj.action,
        entity_type=obj.entity_type,
        entity_id=obj.entity_id,
        detail=obj.detail or {},
        created_at=obj.created_at,
        chain_scope=scope,
        chain_sequence=sequence,
        previous_hash=previous_hash,
        chain_version=CHAIN_VERSION,
    )
    obj.chain_scope = scope
    obj.chain_sequence = sequence
    obj.previous_hash = previous_hash
    obj.event_hash = digest
    obj.chain_version = CHAIN_VERSION
    head.last_sequence = sequence
    head.last_hash = digest
    head.updated_at = obj.created_at


def _guard_audit_events(session: Session, flush_context, instances) -> None:
    for obj in list(session.new):
        if isinstance(obj, AuditEvent):
            _chain_new_event(session, obj)

    for obj in list(session.dirty):
        if isinstance(obj, AuditEvent) and sa_inspect(obj).persistent:
            raise AuditImmutableError(
                "Persisted audit events are append-only and cannot be updated"
            )
    for obj in list(session.deleted):
        if isinstance(obj, AuditEvent) and sa_inspect(obj).persistent:
            raise AuditImmutableError(
                "Persisted audit events are append-only and cannot be deleted"
            )


def _seed_chain_head(mapper, connection, target: Organisation) -> None:
    table = AuditChainHead.__table__
    connection.execute(
        table.insert().values(
            scope_key=target.id,
            organisation_id=target.id,
            last_sequence=0,
            last_hash=None,
            updated_at=utcnow(),
        )
    )


def install_audit_integrity_guard() -> None:
    global _guard_installed
    if _guard_installed:
        return
    event.listen(Session, "before_flush", _guard_audit_events)
    event.listen(Organisation, "after_insert", _seed_chain_head)
    _guard_installed = True
