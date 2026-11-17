"""Company-scoped supplier/customer email routing and document preview API.

Drafts are never transmitted. Sending requires a separate approved provider
integration and must not be inferred from successful creation of a draft.
"""
from flask import Blueprint, g, jsonify, request

from ledgerone.modules.commercial.communications import CommercialCommunicationService
from ledgerone.security import require_api

api_bp = Blueprint("commercial_communication_api", __name__,
                   url_prefix="/api/v1/commercial/communications")


@api_bp.post("/supplier/<party_id>/contacts")
@require_api("purchases.write")
def add_supplier_contact(party_id):
    return _add_route("supplier", party_id)


@api_bp.post("/customer/<party_id>/contacts")
@require_api("sales.write")
def add_customer_contact(party_id):
    return _add_route("customer", party_id)


def _add_route(party_type, party_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = CommercialCommunicationService.add_route(
            g.access_context, party_type=party_type, party_id=party_id,
            purpose=payload.get("purpose"), email=payload.get("email"),
            contact_name=payload.get("contact_name"))
        return jsonify({"id": row.id, "purpose": row.purpose,
                        "email": row.email, "contact_name": row.contact_name}), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/supplier/<party_id>/contacts")
@require_api("purchases.read")
def supplier_contacts(party_id):
    return _contacts("supplier", party_id)


@api_bp.get("/customer/<party_id>/contacts")
@require_api("sales.read")
def customer_contacts(party_id):
    return _contacts("customer", party_id)


def _contacts(party_type, party_id):
    try:
        rows = CommercialCommunicationService.routes(
            g.access_context, party_type=party_type, party_id=party_id,
            purpose=request.args.get("purpose"))
        return jsonify({"contacts": [
            {"id": row.id, "purpose": row.purpose,
             "email": row.email, "contact_name": row.contact_name} for row in rows]})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/document/<document_id>/draft")
@require_api("purchases.write")
def purchase_document_draft(document_id):
    # The company and actual document type/permission are checked in the
    # service; this route is purchase-specific and never sends email.
    return _draft(document_id)


@api_bp.post("/sales-document/<document_id>/draft")
@require_api("sales.write")
def sales_document_draft(document_id):
    return _draft(document_id)


def _draft(document_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = CommercialCommunicationService.draft_document_email(
            g.access_context, document_id=document_id,
            idempotency_key=payload.get("idempotency_key"),
            subject=payload.get("subject"), body=payload.get("body"))
        return jsonify({
            "id": row.id, "document_id": row.document_id,
            "recipients": row.recipients_json, "subject": row.subject,
            "body": row.body, "status": row.status,
            "sent": False,
        }), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
