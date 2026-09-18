from datetime import date

from flask import Blueprint, Response, abort, render_template, request, url_for
from flask_login import login_required

from ledgerone.modules.audit.services import AuditService
from ledgerone.security import browser_context, require_module
from ledgerone.services.audit_integrity import AuditIntegrityService

bp = Blueprint("audit", __name__, url_prefix="/audit")


def _raw_filters():
    return {
        "module_id": request.args.get("module_id", "").strip(),
        "action": request.args.get("action", "").strip(),
        "actor_type": request.args.get("actor_type", "").strip(),
        "entity_type": request.args.get("entity_type", "").strip(),
        "from_date": request.args.get("from_date", "").strip(),
        "to_date": request.args.get("to_date", "").strip(),
        "text": request.args.get("text", "").strip(),
    }


def _service_filters(raw: dict):
    return {
        "module_id": raw["module_id"] or None,
        "action": raw["action"] or None,
        "actor_type": raw["actor_type"] or None,
        "entity_type": raw["entity_type"] or None,
        "from_date": date.fromisoformat(raw["from_date"]) if raw["from_date"] else None,
        "to_date": date.fromisoformat(raw["to_date"]) if raw["to_date"] else None,
        "text": raw["text"] or None,
    }


@bp.get("")
@bp.get("/")
@login_required
@require_module("audit")
def index():
    context = browser_context()
    raw = _raw_filters()
    try:
        filters = _service_filters(raw)
    except ValueError:
        filters = _service_filters({**raw, "from_date": "", "to_date": ""})
        raw["from_date"] = ""
        raw["to_date"] = ""

    page = max(1, request.args.get("page", 1, type=int))
    per_page = 100
    try:
        rows, total = AuditService.search(
            context,
            limit=per_page,
            offset=(page - 1) * per_page,
            **filters,
        )
        options = AuditService.filter_options(context)
    except PermissionError:
        abort(403)

    base_args = {key: value for key, value in raw.items() if value}
    previous_url = (
        url_for("audit.index", page=page - 1, **base_args)
        if page > 1 else None
    )
    next_url = (
        url_for("audit.index", page=page + 1, **base_args)
        if page * per_page < total else None
    )
    return render_template(
        "audit/index.html",
        events=rows,
        total=total,
        page=page,
        filters=raw,
        options=options,
        previous_url=previous_url,
        next_url=next_url,
        export_url=url_for("audit.export", **base_args),
    )


@bp.get("/export")
@login_required
@require_module("audit")
def export():
    context = browser_context()
    try:
        csv_text = AuditService.export_csv(context, **_service_filters(_raw_filters()))
    except PermissionError:
        abort(403)
    except ValueError:
        abort(400)
    filename = f"ledgerone-audit-{date.today().isoformat()}.csv"
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.get("/integrity")
@login_required
@require_module("audit")
def integrity():
    context = browser_context()
    try:
        result = AuditIntegrityService.verify(context)
    except (PermissionError, ValueError):
        abort(403)
    return render_template("audit/integrity.html", integrity=result)
