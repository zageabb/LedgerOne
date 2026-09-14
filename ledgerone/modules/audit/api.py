from datetime import date

from flask import Blueprint, Response, g, jsonify, request

from ledgerone.modules.audit.services import AuditService
from ledgerone.security import require_api

api_bp = Blueprint("audit_api", __name__, url_prefix="/api/v1/audit")


def _filters_from_request():
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    return {
        "module_id": request.args.get("module_id") or None,
        "action": request.args.get("action") or None,
        "actor_type": request.args.get("actor_type") or None,
        "entity_type": request.args.get("entity_type") or None,
        "from_date": date.fromisoformat(from_date) if from_date else None,
        "to_date": date.fromisoformat(to_date) if to_date else None,
        "text": request.args.get("text") or None,
    }


@api_bp.get("")
@require_api("audit.read")
def events():
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
        rows, total = AuditService.search(
            g.access_context,
            limit=limit,
            offset=offset,
            **_filters_from_request(),
        )
        return jsonify(
            {
                "events": [AuditService.serialise(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
    except (PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/export")
@require_api("audit.export")
def export():
    try:
        csv_text = AuditService.export_csv(g.access_context, **_filters_from_request())
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="ledgerone-audit.csv"'},
        )
    except (PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
