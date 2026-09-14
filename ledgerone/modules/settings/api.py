from flask import Blueprint, g, jsonify, request

from ledgerone.modules.ai.configuration import AIConfiguration
from ledgerone.modules.settings.services import SettingsService
from ledgerone.security import require_api

api_bp = Blueprint("settings_api", __name__, url_prefix="/api/v1/settings")


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
        state = SettingsService.set_module_enabled(
            g.access_context, module_id, bool(payload.get("enabled", True))
        )
        return jsonify({"module_id": state.module_id, "enabled": state.enabled})
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
        )
        return jsonify({"id": row.id, "token": token}), 201
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
