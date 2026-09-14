from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps

from flask import abort, g, jsonify, request, session
from flask_login import current_user

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Membership
from ledgerone.module_registry import module_registry
from ledgerone.services.context import AccessContext


def _current_membership():
    if not current_user.is_authenticated:
        return None
    org_id = session.get("organisation_id")
    query = Membership.query.filter_by(user_id=current_user.id, is_active=True)
    if org_id:
        membership = query.filter_by(organisation_id=org_id).first()
        if membership:
            return membership
    membership = query.order_by(Membership.created_at.asc()).first()
    if membership:
        session["organisation_id"] = membership.organisation_id
    return membership


def browser_context() -> AccessContext | None:
    membership = _current_membership()
    if not membership:
        return None
    full_access = membership.role in {"owner", "admin"}
    return AccessContext(
        identity_type="user",
        organisation_id=membership.organisation_id,
        user_id=current_user.id,
        full_access=full_access,
        permissions=frozenset(membership.permissions or []),
    )


def _normalise_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bearer_context() -> AccessContext | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "lo":
        return None
    record = db.session.get(ApiKey, parts[1])
    if not record or not record.is_active or not record.verify_token(token):
        return None
    expires_at = _normalise_utc(record.expires_at)
    if expires_at and expires_at <= datetime.now(timezone.utc):
        return None
    record.last_used_at = datetime.now(timezone.utc)
    db.session.commit()
    return AccessContext(
        identity_type="api_key",
        organisation_id=record.organisation_id,
        api_key_id=record.id,
        full_access=record.full_access,
        permissions=frozenset(record.permissions or []),
    )


def resolve_request_context() -> AccessContext | None:
    return _bearer_context() or browser_context()


def require_api(permission: str | None = None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            context = resolve_request_context()
            if not context:
                return jsonify({"error": "authentication_required"}), 401
            if permission and not context.can(permission):
                return jsonify({"error": "forbidden", "permission": permission}), 403
            g.access_context = context
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_module(module_id: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            context = browser_context()
            if not context:
                abort(401)
            if not module_registry.is_enabled(context.organisation_id, module_id):
                abort(404)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
