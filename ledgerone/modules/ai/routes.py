from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.modules.ai.knowledge import KnowledgeError, KnowledgeService
from ledgerone.modules.ai.models import AIInteraction
from ledgerone.modules.ai.services import LocalAIError, LocalAIService
from ledgerone.security import browser_context, require_module

bp = Blueprint("ai", __name__, url_prefix="/ai")


def _require_permission(context, permission: str):
    if not context or not context.can(permission):
        abort(403)


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("ai")
def index():
    context = browser_context()
    _require_permission(context, "ai.use")
    organisation = db.session.get(Organisation, context.organisation_id)
    if not organisation:
        abort(404)

    if request.method == "POST":
        prompt = request.form.get("prompt", "").strip()
        conversation_id = request.form.get("conversation_id") or None
        approve_writes = request.form.get("approve_writes") == "1"
        if prompt:
            try:
                result = LocalAIService.chat(
                    context=context,
                    organisation_name=organisation.name,
                    prompt=prompt,
                    conversation_id=conversation_id,
                    approve_writes=approve_writes,
                )
                return redirect(url_for("ai.index", conversation=result["conversation_id"]))
            except LocalAIError as exc:
                flash(f"Local AI error: {exc}", "danger")

    conversations = LocalAIService.list_conversations(context)
    active_conversation = None
    interactions = []

    requested_id = request.args.get("conversation")
    start_new = request.args.get("new") == "1"
    if requested_id:
        try:
            active_conversation = LocalAIService.get_conversation(context, requested_id)
        except LocalAIError:
            abort(404)
    elif conversations and not start_new:
        active_conversation = conversations[0]

    if active_conversation:
        interactions = (
            AIInteraction.query.filter_by(
                organisation_id=context.organisation_id,
                conversation_id=active_conversation.id,
            )
            .order_by(AIInteraction.created_at.asc())
            .all()
        )

    return render_template(
        "ai/index.html",
        ai_status=LocalAIService.status(context.organisation_id),
        conversations=conversations,
        active_conversation=active_conversation,
        interactions=interactions,
        can_manage_knowledge=context.can("ai.knowledge.manage"),
        can_read_knowledge=context.can("ai.knowledge.read"),
    )


@bp.post("/conversations/<conversation_id>/rename")
@login_required
@require_module("ai")
def rename_conversation(conversation_id):
    context = browser_context()
    _require_permission(context, "ai.use")
    try:
        LocalAIService.rename_conversation(
            context,
            conversation_id,
            request.form.get("title", ""),
        )
        flash("Conversation renamed.", "success")
    except LocalAIError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ai.index", conversation=conversation_id))


@bp.post("/conversations/<conversation_id>/archive")
@login_required
@require_module("ai")
def archive_conversation(conversation_id):
    context = browser_context()
    _require_permission(context, "ai.use")
    try:
        LocalAIService.archive_conversation(context, conversation_id)
        flash("Conversation archived.", "success")
    except LocalAIError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ai.index", new=1))


@bp.route("/knowledge", methods=["GET", "POST"])
@login_required
@require_module("ai")
def knowledge():
    context = browser_context()
    if request.method == "POST":
        _require_permission(context, "ai.knowledge.manage")
        try:
            uploaded = request.files.get("file")
            title = request.form.get("title", "").strip()
            text = request.form.get("content", "").strip()
            if uploaded and uploaded.filename:
                KnowledgeService.create_upload(context, uploaded, title=title or None)
            elif text:
                KnowledgeService.create_text_source(
                    context,
                    title=title or "Knowledge note",
                    content=text,
                    media_type="text/plain",
                )
            else:
                raise KnowledgeError("Add a file or paste Knowledge text.")
            flash("Knowledge source added and indexed.", "success")
            return redirect(url_for("ai.knowledge"))
        except (KnowledgeError, PermissionError) as exc:
            flash(str(exc), "danger")

    if not (context.can("ai.knowledge.read") or context.can("ai.knowledge.manage")):
        abort(403)
    return render_template(
        "ai/knowledge.html",
        sources=KnowledgeService.list_sources(context),
        can_manage=context.can("ai.knowledge.manage"),
    )


@bp.post("/knowledge/<source_id>/toggle")
@login_required
@require_module("ai")
def toggle_knowledge(source_id):
    context = browser_context()
    _require_permission(context, "ai.knowledge.manage")
    enabled = request.form.get("enabled") == "1"
    try:
        KnowledgeService.set_enabled(context, source_id, enabled)
        flash("Knowledge source updated.", "success")
    except KnowledgeError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ai.knowledge"))


@bp.post("/knowledge/<source_id>/reindex")
@login_required
@require_module("ai")
def reindex_knowledge(source_id):
    context = browser_context()
    _require_permission(context, "ai.knowledge.manage")
    try:
        KnowledgeService.reindex(context, source_id)
        flash("Knowledge source re-indexed.", "success")
    except KnowledgeError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ai.knowledge"))


@bp.post("/knowledge/<source_id>/delete")
@login_required
@require_module("ai")
def delete_knowledge(source_id):
    context = browser_context()
    _require_permission(context, "ai.knowledge.manage")
    try:
        KnowledgeService.delete(context, source_id)
        flash("Knowledge source deleted.", "success")
    except KnowledgeError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ai.knowledge"))
