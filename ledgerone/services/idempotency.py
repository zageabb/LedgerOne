from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from flask import jsonify, make_response, request
from sqlalchemy.exc import IntegrityError

from ledgerone.extensions import db
from ledgerone.models.core import IdempotencyRecord, utcnow


class IdempotencyError(ValueError):
    pass


class IdempotencyService:
    RETENTION_DAYS = 90

    @staticmethod
    def _fingerprint() -> str:
        payload = request.get_json(silent=True)
        body = (
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            if payload is not None
            else request.get_data(cache=True, as_text=True)
        )
        query = "&".join(
            f"{key}={value}"
            for key, values in sorted(request.args.lists())
            for value in values
        )
        canonical = "\n".join([request.method.upper(), request.path, query, body])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _result_reference(payload):
        if not isinstance(payload, dict):
            return None, None
        for key, entity_type in (
            ("id", "entity"),
            ("journal_id", "journal"),
            ("workflow_instance_id", "workflow_instance"),
            ("replacement", "workflow_instance"),
        ):
            value = payload.get(key)
            if key == "replacement" and isinstance(value, dict):
                value = value.get("id")
            if value:
                return entity_type, str(value)
        return None, None

    @staticmethod
    def execute(context, operation: str, fn, *args, **kwargs):
        if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
            return fn(*args, **kwargs)

        key = (request.headers.get("Idempotency-Key") or "").strip()
        if not key:
            return fn(*args, **kwargs)
        if len(key) > 255:
            return jsonify({"error": "idempotency_key_too_long"}), 400

        source_system = (request.headers.get("X-Source-System") or "").strip() or None
        source_reference = (request.headers.get("X-Source-Reference") or "").strip() or None
        if bool(source_system) != bool(source_reference):
            return jsonify({
                "error": "source_identity_incomplete",
                "message": "X-Source-System and X-Source-Reference must be supplied together",
            }), 400

        fingerprint = IdempotencyService._fingerprint()
        query = IdempotencyRecord.query.filter_by(
            organisation_id=context.organisation_id,
            operation=operation,
            idempotency_key=key,
        )
        existing = query.first()
        if existing:
            return IdempotencyService._replay(existing, fingerprint)

        now = utcnow()
        record = IdempotencyRecord(
            organisation_id=context.organisation_id,
            operation=operation,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            source_system=source_system,
            source_reference=source_reference,
            status="in_progress",
            expires_at=now + timedelta(days=IdempotencyService.RETENTION_DAYS),
        )
        db.session.add(record)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing = query.first()
            if not existing and source_system and source_reference:
                existing = IdempotencyRecord.query.filter_by(
                    organisation_id=context.organisation_id,
                    operation=operation,
                    source_system=source_system,
                    source_reference=source_reference,
                ).first()
            if existing:
                return IdempotencyService._replay(existing, fingerprint)
            raise

        try:
            response = make_response(fn(*args, **kwargs))
        except Exception:
            db.session.rollback()
            db.session.delete(record)
            db.session.commit()
            raise

        if response.status_code >= 400:
            db.session.delete(record)
            db.session.commit()
            return response

        payload = response.get_json(silent=True)
        entity_type, entity_id = IdempotencyService._result_reference(payload)
        record.status = "completed"
        record.response_status = response.status_code
        record.response_json = payload
        record.result_entity_type = entity_type
        record.result_entity_id = entity_id
        record.completed_at = utcnow()
        db.session.commit()
        return response

    @staticmethod
    def _replay(record: IdempotencyRecord, fingerprint: str):
        if record.request_fingerprint != fingerprint:
            return jsonify({
                "error": "idempotency_conflict",
                "message": "This Idempotency-Key was already used with a different request",
            }), 409
        if record.status != "completed":
            return jsonify({
                "error": "idempotency_in_progress",
                "message": "A request with this Idempotency-Key is already in progress",
            }), 409
        response = jsonify(record.response_json)
        response.status_code = record.response_status or 200
        response.headers["Idempotency-Replayed"] = "true"
        return response

    @staticmethod
    def cleanup_expired() -> int:
        count = IdempotencyRecord.query.filter(
            IdempotencyRecord.expires_at < utcnow()
        ).delete(synchronize_session=False)
        if count:
            db.session.commit()
        return count
