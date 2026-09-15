from flask import Blueprint, g, jsonify, request

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.modules.ai.configuration import AIConfiguration
from ledgerone.modules.ai.knowledge import KnowledgeError, KnowledgeService
from ledgerone.modules.ai.services import LocalAIError, LocalAIService
from ledgerone.modules.ai.tools import available_tools
from ledgerone.security import require_api

api_bp = Blueprint("ai_api", __name__, url_prefix="/api/v1/ai")


@api_bp.get("/status")
@require_api("ai.read")
def status():
    return jsonify(LocalAIService.status(g.access_context.organisation_id))


@api_bp.get("/tools")
@require_api("ai.read")
def tools():
    rows = available_tools(g.access_context, allow_writes=False)
    return jsonify(
        {
            "tools": [
                {
                    "name": name,
                    "module": spec.module_id,
                    "description": spec.description,
                    "write": spec.write,
                    "permission": spec.permission,
                }
                for name, spec in rows.items()
            ]
        }
    )


@api_bp.get("/conversations")
@require_api("ai.use")
def conversations():
    rows = LocalAIService.list_conversations(g.access_context)
    return jsonify(
        {
            "conversations": [
                {
                    "id": row.id,
                    "title": row.title,
                    "archived": row.archived,
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
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
            context=g.access_context,
            organisation_name=organisation.name,
            prompt=prompt,
            conversation_id=payload.get("conversation_id") or None,
            approve_writes=payload.get("approve_writes") is True,
        )
        return jsonify(result)
    except LocalAIError as exc:
        return jsonify({"error": str(exc)}), 502


@api_bp.get("/knowledge")
@require_api("ai.knowledge.read")
def knowledge_list():
    return jsonify(
        {
            "sources": [
                {
                    "id": row.id,
                    "title": row.title,
                    "filename": row.filename,
                    "media_type": row.media_type,
                    "enabled": row.enabled,
                    "status": row.status,
                    "chunks": len(row.chunks),
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in KnowledgeService.list_sources(g.access_context)
            ]
        }
    )


@api_bp.post("/knowledge")
@require_api("ai.knowledge.manage")
def knowledge_create():
    payload = request.get_json(silent=True) or {}
    try:
        row = KnowledgeService.create_text_source(
            g.access_context,
            title=str(payload.get("title") or "").strip(),
            content=str(payload.get("content") or ""),
            filename=str(payload.get("filename") or "").strip() or None,
            media_type=str(payload.get("media_type") or "text/plain"),
        )
    except KnowledgeError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": row.id, "title": row.title, "status": row.status}), 201


@api_bp.post("/knowledge/<source_id>/reindex")
@require_api("ai.knowledge.manage")
def knowledge_reindex(source_id):
    try:
        row = KnowledgeService.reindex(g.access_context, source_id)
    except KnowledgeError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"id": row.id, "status": row.status})


@api_bp.delete("/knowledge/<source_id>")
@require_api("ai.knowledge.manage")
def knowledge_delete(source_id):
    try:
        KnowledgeService.delete(g.access_context, source_id)
    except KnowledgeError as exc:
        return jsonify({"error": str(exc)}), 404
    return "", 204
