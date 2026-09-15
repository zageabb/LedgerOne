from flask import Blueprint, g, jsonify, request, send_file

from ledgerone.modules.documents.services import DocumentError, DocumentService
from ledgerone.security import require_api
from ledgerone.services.audit_trace import AuditTraceError, AuditTraceService

api_bp = Blueprint("documents_api", __name__, url_prefix="/api/v1/documents")


@api_bp.get("")
@require_api("documents.read")
def list_documents():
    rows = DocumentService.list_documents(
        g.access_context,
        entity_type=request.args.get("entity_type") or None,
        entity_id=request.args.get("entity_id") or None,
        module_id=request.args.get("module_id") or None,
        limit=min(int(request.args.get("limit", 200)), 500),
    )
    return jsonify({"documents": [DocumentService.serialise(row) for row in rows]})


@api_bp.get("/audit-trace")
@require_api("documents.read")
def audit_trace():
    try:
        trace = AuditTraceService.build(
            g.access_context,
            request.args.get("entity_type", ""),
            request.args.get("entity_id", ""),
        )
        return jsonify(trace)
    except (AuditTraceError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/reference")
@require_api("documents.write")
def add_reference():
    payload = request.get_json(silent=True) or {}
    try:
        row = DocumentService.create_reference(
            g.access_context,
            entity_type=payload.get("entity_type", ""),
            entity_id=payload.get("entity_id", ""),
            reference_url=payload.get("reference_url", ""),
            title=payload.get("title"),
        )
        return jsonify(DocumentService.serialise(row)), 201
    except (DocumentError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/upload")
@require_api("documents.write")
def upload_document():
    try:
        row = DocumentService.create_file(
            g.access_context,
            entity_type=request.form.get("entity_type", ""),
            entity_id=request.form.get("entity_id", ""),
            upload=request.files.get("file"),
            title=request.form.get("title"),
        )
        return jsonify(DocumentService.serialise(row)), 201
    except (DocumentError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/<document_id>")
@require_api("documents.read")
def get_document(document_id):
    try:
        row = DocumentService.get_document(g.access_context, document_id)
        return jsonify(DocumentService.serialise(row))
    except (DocumentError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 404


@api_bp.get("/<document_id>/content")
@require_api("documents.read")
def document_content(document_id):
    try:
        row = DocumentService.get_document(g.access_context, document_id)
        path = DocumentService.file_path(g.access_context, document_id)
        return send_file(
            path,
            as_attachment=True,
            download_name=row.original_filename or row.title,
            mimetype=row.content_type,
        )
    except (DocumentError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 404
