from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required

from ledgerone.modules.documents.services import DocumentError, DocumentService
from ledgerone.security import browser_context, require_module

bp = Blueprint("documents", __name__, url_prefix="/documents")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("documents")
def index():
    context = browser_context()
    entity_type = (request.values.get("entity_type") or "").strip()
    entity_id = (request.values.get("entity_id") or "").strip()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "upload":
                DocumentService.create_file(
                    context,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    upload=request.files.get("file"),
                    title=request.form.get("title"),
                )
                flash("Source document uploaded.", "success")
            elif action == "reference":
                DocumentService.create_reference(
                    context,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    reference_url=request.form.get("reference_url", ""),
                    title=request.form.get("title"),
                )
                flash("Source reference added.", "success")
            return redirect(
                url_for("documents.index", entity_type=entity_type, entity_id=entity_id)
            )
        except (DocumentError, PermissionError, ValueError) as exc:
            flash(str(exc), "danger")

    rows = DocumentService.list_documents(
        context,
        entity_type=entity_type or None,
        entity_id=entity_id or None,
        limit=300,
    )
    return render_template(
        "documents/index.html",
        documents=rows,
        entity_type=entity_type,
        entity_id=entity_id,
        target_types=DocumentService.TARGETS,
    )


@bp.get("/<document_id>/download")
@login_required
@require_module("documents")
def download(document_id):
    context = browser_context()
    try:
        row = DocumentService.get_document(context, document_id)
        path = DocumentService.file_path(context, document_id)
        return send_file(
            path,
            as_attachment=True,
            download_name=row.original_filename or row.title,
            mimetype=row.content_type,
        )
    except (DocumentError, PermissionError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("documents.index"))
