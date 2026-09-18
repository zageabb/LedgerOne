from sqlalchemy import text

import pytest

from ledgerone.extensions import db
from ledgerone.models.audit import AuditChainHead, AuditEvent
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.services.audit import record_audit_event
from ledgerone.services.audit_integrity import (
    AuditImmutableError,
    AuditIntegrityService,
)
from ledgerone.services.context import AccessContext


def _context():
    organisation = Organisation.query.one()
    return AccessContext.system(organisation.id)


def _record(context, action: str):
    row = record_audit_event(
        context,
        module_id="audit_test",
        action=action,
        entity_type="test_record",
        entity_id=action,
        detail={"action": action, "value": 1},
    )
    db.session.commit()
    return row


def test_legacy_direct_audit_constructor_is_chained_at_flush(app):
    with app.app_context():
        context = _context()
        row = AuditEvent(
            organisation_id=context.organisation_id,
            actor_type="system",
            actor_id=None,
            module_id="legacy_test",
            action="direct_constructor",
            entity_type="test_record",
            entity_id="legacy-1",
            detail={"legacy": True},
        )
        db.session.add(row)
        db.session.commit()

        assert row.chain_scope == context.organisation_id
        assert row.chain_sequence >= 1
        assert row.event_hash and len(row.event_hash) == 64
        assert AuditIntegrityService.verify(context)["valid"] is True


def test_audit_events_are_append_only_through_orm(app):
    with app.app_context():
        context = _context()
        row = _record(context, "immutable_created")
        event_id = row.id

        row.action = "tampered"
        with pytest.raises(AuditImmutableError, match="cannot be updated"):
            db.session.commit()
        db.session.rollback()

        row = db.session.get(AuditEvent, event_id)
        db.session.delete(row)
        with pytest.raises(AuditImmutableError, match="cannot be deleted"):
            db.session.commit()
        db.session.rollback()


def test_multiple_audit_events_share_one_transaction_chain_cleanly(app):
    with app.app_context():
        context = _context()
        first = record_audit_event(
            context,
            module_id="audit_test",
            action="same_transaction_one",
            detail={"step": 1},
        )
        second = record_audit_event(
            context,
            module_id="audit_test",
            action="same_transaction_two",
            detail={"step": 2},
        )
        db.session.commit()

        assert second.chain_sequence == first.chain_sequence + 1
        assert second.previous_hash == first.event_hash
        assert AuditIntegrityService.verify(context)["valid"] is True


def test_audit_chain_head_rolls_back_with_business_transaction(app):
    with app.app_context():
        context = _context()
        before = AuditIntegrityService.verify(context)
        event = record_audit_event(
            context,
            module_id="audit_test",
            action="rolled_back_event",
            detail={"should_persist": False},
        )
        event_id = event.id
        db.session.flush()
        db.session.rollback()

        assert db.session.get(AuditEvent, event_id) is None
        after = AuditIntegrityService.verify(context)
        assert after["valid"] is True
        assert after["last_sequence"] == before["last_sequence"]
        assert after["last_hash"] == before["last_hash"]


def test_audit_chain_verifies_for_normal_events(app):
    with app.app_context():
        context = _context()
        _record(context, "chain_one")
        _record(context, "chain_two")
        result = AuditIntegrityService.verify(context)

        assert result["valid"] is True
        assert result["checked_events"] >= 2
        assert result["last_sequence"] == result["checked_events"]
        assert len(result["last_hash"]) == 64

        head = db.session.get(AuditChainHead, context.organisation_id)
        assert head is not None
        assert head.last_sequence == result["last_sequence"]
        assert head.last_hash == result["last_hash"]


def test_integrity_verifier_detects_raw_event_tamper(app):
    with app.app_context():
        context = _context()
        row = _record(context, "raw_tamper_target")
        assert AuditIntegrityService.verify(context)["valid"] is True

        db.session.execute(
            text("UPDATE audit_events SET action = :action WHERE id = :event_id"),
            {"action": "raw_tampered", "event_id": row.id},
        )
        db.session.commit()
        db.session.expire_all()

        result = AuditIntegrityService.verify(context)
        assert result["valid"] is False
        assert result["first_error"] == "event_hash_mismatch"
        assert result["event_id"] == row.id


def test_integrity_verifier_detects_deleted_chain_tail(app):
    with app.app_context():
        context = _context()
        _record(context, "tail_one")
        tail = _record(context, "tail_two")
        assert AuditIntegrityService.verify(context)["valid"] is True

        db.session.execute(
            text("DELETE FROM audit_events WHERE id = :event_id"),
            {"event_id": tail.id},
        )
        db.session.commit()
        db.session.expire_all()

        result = AuditIntegrityService.verify(context)
        assert result["valid"] is False
        assert result["first_error"] == "chain_head_mismatch"


def test_audit_export_is_itself_audited_and_chain_remains_valid(client, app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="audit-integrity-export",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()

    response = client.get(
        "/api/v1/audit/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "chain_sequence" in response.get_data(as_text=True)
    assert "event_hash" in response.get_data(as_text=True)

    with app.app_context():
        organisation = Organisation.query.one()
        context = AccessContext.system(organisation.id)
        exported = (
            AuditEvent.query.filter_by(
                organisation_id=organisation.id,
                module_id="audit",
                action="audit_exported",
            )
            .order_by(AuditEvent.chain_sequence.desc())
            .first()
        )
        assert exported is not None
        assert exported.detail["row_count"] >= 0
        assert AuditIntegrityService.verify(context)["valid"] is True


def test_audit_integrity_api_reports_chain_health(client, app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="audit-integrity-read",
            organisation_id=organisation.id,
            permissions=["audit.read"],
        )
        db.session.add(key)
        db.session.commit()

    response = client.get(
        "/api/v1/audit/integrity",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["checked_events"] >= 0


def test_audit_integrity_browser_route_is_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/audit/integrity" in rules
    assert "/api/v1/audit/integrity" in rules
