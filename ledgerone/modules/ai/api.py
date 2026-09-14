from flask import Blueprint, g, jsonify, request

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.modules.ai.services import LocalAIError, LocalAIService
from ledgerone.modules.ai.tools import available_tools
from ledgerone.security import require_api

api_bp = Blueprint("ai_api", __name__, url_prefix="/api/v1/ai")


@api_bp.get("/status")
@require_api("ai.read")
def status():
    return jsonify(LocalAIService.status())


@api_bp.get("/tools")
@require_api("ai.read")
def tools():
    rows = available_tools(g.access_context.organisation_id)
    return jsonify(
        {
            "tools": [
                {
                    "name": name,
                    "module": spec.module_id,
                    "description": spec.description,
                    "write": spec.write,
                }
                for name, spec in rows.items()
            ]
        }
    )


@api_bp.post("/chat")
@require_api("ai.use")
def chat():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt_required"}), 400
    organisation = db.session.get(Organisation, g.access_context.organisation_id)
    if not organisation:
        return jsonify({"error": "organisation_not_found"}), 404
    try:
        result = LocalAIService.chat(
            organisation_id=organisation.id,
            organisation_name=organisation.name,
            user_id=g.access_context.user_id,
            prompt=prompt,
        )
        return jsonify(result)
    except LocalAIError as exc:
        return jsonify({"error": str(exc)}), 502
