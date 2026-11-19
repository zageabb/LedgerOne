"""Authenticated ERP-000 acknowledgement, GRN and delivery-note API."""
from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.security import require_api

api_bp = Blueprint("commercial_api", __name__, url_prefix="/api/v1/commercial")


def _serialize(row):
    return {
        "id": row.id, "organisation_id": row.organisation_id,
        "document_type": row.document_type, "order_id": row.order_id,
        "document_number": row.document_number, "revision": row.revision,
        "status": row.status, "document_date": row.document_date.isoformat(),
        "external_reference": row.external_reference,
        "response_status": row.response_status,
        "confirmed_date": row.confirmed_date.isoformat() if row.confirmed_date else None,
        "lines": [
            {"id": line.id, "order_line_id": line.order_line_id,
             "description": line.description, "quantity": str(line.quantity),
             "unit_price": str(line.unit_price),
             "expected_date": line.expected_date.isoformat() if line.expected_date else None}
            for line in row.lines
        ],
    }


@api_bp.get("/purchases/orders/<order_id>/documents/<document_type>")
@require_api("purchases.read")
def purchase_documents(order_id, document_type):
    if document_type not in {"po_ack", "grn"}:
        return jsonify({"error": "Invalid purchase document type"}), 400
    try:
        items = CommercialDocumentService.list_for_order(
            g.access_context, document_type=document_type, order_id=order_id)
        return jsonify({"documents": [_serialize(item) for item in items]})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/sales/orders/<order_id>/documents/<document_type>")
@require_api("sales.read")
def sales_documents(order_id, document_type):
    if document_type not in {"so_ack", "delivery_note"}:
        return jsonify({"error": "Invalid sales document type"}), 400
    try:
        items = CommercialDocumentService.list_for_order(
            g.access_context, document_type=document_type, order_id=order_id)
        return jsonify({"documents": [_serialize(item) for item in items]})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/purchases/orders/<order_id>/documents/<document_type>")
@require_api("purchases.write")
def create_purchase_document(order_id, document_type):
    if document_type not in {"po_ack", "grn"}:
        return jsonify({"error": "Invalid purchase document type"}), 400
    return _create(order_id, document_type)


@api_bp.post("/sales/orders/<order_id>/documents/<document_type>")
@require_api("sales.write")
def create_sales_document(order_id, document_type):
    if document_type not in {"so_ack", "delivery_note"}:
        return jsonify({"error": "Invalid sales document type"}), 400
    return _create(order_id, document_type)


def _create(order_id, document_type):
    payload = request.get_json(silent=True) or {}
    try:
        lines = payload.get("lines")
        if lines is not None:
            lines = [
                {**row, "expected_date": date.fromisoformat(row["expected_date"])
                 if row.get("expected_date") else None}
                for row in lines
            ]
        document = CommercialDocumentService.create(
            g.access_context, document_type=document_type,
            order_id=order_id,
            document_date=date.fromisoformat(
                payload.get("document_date") or date.today().isoformat()),
            lines=lines, external_reference=payload.get("external_reference"),
            metadata=payload.get("metadata"))
        return jsonify(_serialize(document)), 201
    except (ValueError, KeyError, TypeError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/purchases/acknowledgements/<document_id>/response")
@require_api("purchases.write")
def record_po_response(document_id):
    payload = request.get_json(silent=True) or {}
    try:
        document = CommercialDocumentService.respond_to_po_ack(
            g.access_context, document_id,
            response_status=payload.get("response_status", ""),
            confirmed_date=date.fromisoformat(payload["confirmed_date"])
            if payload.get("confirmed_date") else None,
            supplier_reference=payload.get("supplier_reference"))
        return jsonify(_serialize(document))
    except (ValueError, KeyError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/purchases/grn/<grn_id>/accounting-preview")
@require_api("purchases.read")
def grn_accounting_preview(grn_id):
    from ledgerone.modules.commercial.grn_accounting import GRNAccountingPreviewService
    try:
        return jsonify(GRNAccountingPreviewService.preview(g.access_context, grn_id=grn_id))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/purchases/orders/<order_id>/receipt-allocations")
@require_api("purchases.read")
def purchase_receipt_allocations(order_id):
    """Read-only quantities; never authorises billing or GRNI clearing."""
    from ledgerone.modules.commercial.receipt_allocations import PurchaseReceiptAllocationService
    try:
        return jsonify(PurchaseReceiptAllocationService.summary(
            g.access_context, order_id=order_id))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/purchases/orders/<order_id>/bill-drafts")
@require_api("purchases.write")
def create_po_bill_draft(order_id):
    """Capture multi-line PO-linked invoice details without posting to ledger."""
    from ledgerone.modules.commercial.bill_drafts import PurchaseBillDraftService
    payload = request.get_json(silent=True) or {}
    try:
        bill = PurchaseBillDraftService.create(
            g.access_context,
            order_id=order_id,
            supplier_invoice_reference=payload.get("supplier_invoice_reference"),
            bill_date=date.fromisoformat(payload["bill_date"]),
            due_date=date.fromisoformat(payload["due_date"])
            if payload.get("due_date") else None,
            bill_number=payload.get("bill_number"),
            lines=payload["lines"],
        )
        return jsonify({
            "id": bill.id, "bill_number": bill.bill_number,
            "supplier_invoice_reference": bill.supplier_invoice_reference,
            "purchase_order_id": order_id, "status": bill.status,
            "posted_journal_id": bill.posted_journal_id,
            "subtotal": str(bill.subtotal), "tax_total": str(bill.tax_total),
            "total": str(bill.total), "currency": bill.currency,
            "lines": [{
                "id": line.id, "line_number": line.line_number,
                "source_purchase_order_line_id":
                    (line.dimensions or {}).get("source_purchase_order_line_id"),
                "quantity": str(line.quantity), "unit_price": str(line.unit_price),
                "net_amount": str(line.net_amount), "tax_amount": str(line.tax_amount),
            } for line in bill.lines],
            "posting_authorised": False,
        }), 201
    except (ValueError, KeyError, TypeError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
