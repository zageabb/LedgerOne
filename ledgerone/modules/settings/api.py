from datetime import datetime, time, timezone

from flask import Blueprint, g, jsonify, request

from ledgerone.module_registry import module_registry
from ledgerone.modules.ai.configuration import AIConfiguration
from ledgerone.modules.settings.services import SettingsService
from ledgerone.security import require_api
from ledgerone.services.payment_terms import PaymentTermsService

api_bp = Blueprint("settings_api", __name__, url_prefix="/api/v1/settings")


def _parse_expiry(value):
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if len(text) == 10:
        day = datetime.strptime(text, "%Y-%m-%d").date()
        return datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@api_bp.get("")
@require_api("settings.read")
def get_settings():
    org = SettingsService.organisation(g.access_context)
    modules = SettingsService.module_states(g.access_context)
    return jsonify(
        {
            "organisation": {
                "id": org.id,
                "name": org.name,
                "base_currency": org.base_currency,
                "country_code": org.country_code,
                "fiscal_year_start_month": org.fiscal_year_start_month,
                "fiscal_year_start_day": org.fiscal_year_start_day,
            },
            "payment_terms": PaymentTermsService.get(g.access_context.organisation_id),
            "modules": [
                {
                    "id": item["manifest"].id,
                    "name": item["manifest"].name,
                    "enabled": item["enabled"],
                    "always_on": item["manifest"].always_on,
                    "dependencies": list(item["manifest"].dependencies),
                }
                for item in modules
            ],
            "permissions": SettingsService.permission_catalog(),
            "ai": AIConfiguration.get(g.access_context.organisation_id),
        }
    )


@api_bp.patch("")
@require_api("settings.manage")
def update_settings():
    payload = request.get_json(silent=True) or {}
    org = SettingsService.organisation(g.access_context)
    try:
        updated = SettingsService.update_organisation(
            g.access_context,
            name=payload.get("name", org.name),
            base_currency=payload.get("base_currency", org.base_currency),
            country_code=payload.get("country_code", org.country_code),
            fiscal_year_start_month=payload.get("fiscal_year_start_month", org.fiscal_year_start_month),
            fiscal_year_start_day=payload.get("fiscal_year_start_day", org.fiscal_year_start_day),
        )
        return jsonify({"id": updated.id, "name": updated.name})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/payment-terms")
@require_api("settings.read")
def get_payment_terms():
    return jsonify(PaymentTermsService.get(g.access_context.organisation_id))


@api_bp.patch("/payment-terms")
@require_api("settings.manage")
def update_payment_terms():
    payload = request.get_json(silent=True) or {}
    current = PaymentTermsService.get(g.access_context.organisation_id)
    try:
        updated = PaymentTermsService.update(
            g.access_context,
            customer_days=payload.get("customer_days", current["customer_days"]),
            supplier_days=payload.get("supplier_days", current["supplier_days"]),
        )
        return jsonify(updated)
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/ai")
@require_api("settings.read")
def get_ai_settings():
    config = AIConfiguration.get(g.access_context.organisation_id)
    probe = AIConfiguration.probe(base_url=config["base_url"], timeout=3)
    return jsonify({"settings": config, "connection": probe})


@api_bp.patch("/ai")
@require_api("settings.manage")
def update_ai_settings():
    payload = request.get_json(silent=True) or {}
    current = AIConfiguration.get(g.access_context.organisation_id)
    try:
        updated = AIConfiguration.update(
            g.access_context,
            enabled=payload.get("enabled", current["enabled"]),
            base_url=payload.get("base_url", current["base_url"]),
            model=payload.get("model", current["model"]),
            timeout=payload.get("timeout", current["timeout"]),
            allow_writes=payload.get("allow_writes", current["allow_writes"]),
        )
        return jsonify({"settings": updated})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/ai/test")
@require_api("settings.manage")
def test_ai_settings():
    payload = request.get_json(silent=True) or {}
    current = AIConfiguration.get(g.access_context.organisation_id)
    base_url = payload.get("base_url", current["base_url"])
    try:
        base_url, _, _ = AIConfiguration._validate(
            base_url=base_url,
            model=payload.get("model", current["model"]),
            timeout=payload.get("timeout", current["timeout"]),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result = AIConfiguration.probe(base_url=base_url, timeout=3)
    return jsonify(result), 200 if result["reachable"] else 502


@api_bp.post("/modules/<module_id>")
@require_api("settings.manage")
def set_module(module_id):
    payload = request.get_json(silent=True) or {}
    try:
        enabled = bool(payload.get("enabled", True))
        state = SettingsService.set_module_enabled(
            g.access_context, module_id, enabled
        )
        if enabled:
            module_registry.seed_module_defaults(g.access_context.organisation_id, module_id)
        return jsonify({"module_id": state.module_id, "enabled": state.enabled})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/members")
@require_api("settings.read")
def members():
    rows = SettingsService.list_members(g.access_context)
    return jsonify(
        {
            "members": [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "name": row.user.name,
                    "email": row.user.email,
                    "role": row.role,
                    "permissions": row.permissions or [],
                    "is_active": row.is_active,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/members")
@require_api("settings.manage")
def save_member():
    payload = request.get_json(silent=True) or {}
    try:
        row = SettingsService.save_member(
            g.access_context,
            email=payload.get("email", ""),
            name=payload.get("name", ""),
            role=payload.get("role", "member"),
            permissions=payload.get("permissions") or [],
            password=payload.get("password"),
            active=bool(payload.get("is_active", True)),
        )
        return jsonify({"id": row.id, "user_id": row.user_id, "role": row.role}), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.delete("/members/<membership_id>")
@require_api("settings.manage")
def deactivate_member(membership_id):
    try:
        row = SettingsService.deactivate_member(g.access_context, membership_id)
        return jsonify({"id": row.id, "is_active": row.is_active})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/api-keys")
@require_api("settings.read")
def api_keys():
    rows = SettingsService.list_api_keys(g.access_context)
    return jsonify(
        {
            "api_keys": [
                {
                    "id": row.id,
                    "name": row.name,
                    "full_access": row.full_access,
                    "permissions": row.permissions,
                    "is_active": row.is_active,
                    "created_at": row.created_at.isoformat(),
                    "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                    "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/api-keys")
@require_api("settings.manage")
def create_api_key():
    payload = request.get_json(silent=True) or {}
    try:
        row, token = SettingsService.issue_api_key(
            g.access_context,
            name=payload.get("name", "API key"),
            full_access=bool(payload.get("full_access", False)),
            permissions=payload.get("permissions") or [],
            expires_at=_parse_expiry(payload.get("expires_at")),
        )
        return jsonify(
            {
                "id": row.id,
                "token": token,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
        ), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/api-keys/<key_id>/rotate")
@require_api("settings.manage")
def rotate_api_key(key_id):
    payload = request.get_json(silent=True) or {}
    try:
        row, token = SettingsService.rotate_api_key(
            g.access_context,
            key_id,
            expires_at=_parse_expiry(payload.get("expires_at")),
        )
        return jsonify(
            {
                "id": row.id,
                "token": token,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
        ), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.delete("/api-keys/<key_id>")
@require_api("settings.manage")
def revoke_api_key(key_id):
    try:
        row = SettingsService.revoke_api_key(g.access_context, key_id)
        return jsonify({"id": row.id, "is_active": row.is_active})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
