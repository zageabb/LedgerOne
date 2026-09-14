from flask import Blueprint, flash, render_template, request
from flask_login import login_required

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.modules.ai.models import AIInteraction
from ledgerone.modules.ai.services import LocalAIError, LocalAIService
from ledgerone.security import browser_context, require_module

bp = Blueprint("ai", __name__, url_prefix="/ai")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("ai")
def index():
    context = browser_context()
    organisation = db.session.get(Organisation, context.organisation_id)
    answer = None
    tool_log = []
    prompt = ""

    if request.method == "POST":
        prompt = request.form.get("prompt", "").strip()
        if prompt:
            try:
                result = LocalAIService.chat(
                    organisation_id=organisation.id,
                    organisation_name=organisation.name,
                    user_id=context.user_id,
                    prompt=prompt,
                )
                answer = result["message"]
                tool_log = result["tools"]
            except LocalAIError as exc:
                flash(f"Local AI error: {exc}", "danger")

    history = (
        AIInteraction.query.filter_by(organisation_id=context.organisation_id)
        .order_by(AIInteraction.created_at.desc())
        .limit(12)
        .all()
    )
    return render_template(
        "ai/index.html",
        ai_status=LocalAIService.status(),
        prompt=prompt,
        answer=answer,
        tool_log=tool_log,
        history=history,
    )
