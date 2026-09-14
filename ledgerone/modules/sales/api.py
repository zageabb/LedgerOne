from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.sales.services import SalesService
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError

api_bp = Blueprint("sales_api", __name__, url_prefix="/api/v1/sales")


@api_bp.get("/customers")
@require_api("sales.read")
def customers():
    rows = SalesService.list_customers(g.access_context)
    return jsonify({"customers": [{"id": row.id, "name": row.name, "email": row.email, "phone": row.phone, "is_active": row.is_active} for row in rows]})


@api_bp.post("/customers")
@require_api("sales.write")
def create_customer():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesService.create_customer(g.access_context, name=payload.get("name", ""), email=payload.get("email"), phone=payload.get("phone"))
        return jsonify({"id": row.id, "name": row.name}), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/invoices")
@require_api("sales.read")
def invoices():
    rows = SalesService.list_invoices(g.access_context, min(int(request.args.get("limit", 100)), 500))
    return jsonify({"invoices": [{
        "id": row.id,
        "invoice_number": row.invoice_number,
        "customer_id": row.customer_id,
        "invoice_date": row.invoice_date.isoformat(),
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "currency": row.currency,
        "status": row.status,
        "subtotal": str(row.subtotal),
        "tax_total": str(row.tax_total),
        "total": str(row.total),
        "tax_code_id": row.lines[0].tax_code_id if row.lines else None,
        "allocated": str(SalesService.invoice_allocated(row.id)),
        "outstanding": str(SalesService.invoice_outstanding(row)),
        "posted_journal_id": row.posted_journal_id,
    } for row in rows]})


@api_bp.post("/invoices")
@require_api("sales.write")
def create_invoice():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesService.create_invoice(
            g.access_context,
            customer_id=payload["customer_id"],
            invoice_number=payload["invoice_number"],
            invoice_date=date.fromisoformat(payload.get("invoice_date") or date.today().isoformat()),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
            description=payload.get("description", "Sales"),
            amount=payload["amount"],
            receivable_account_id=payload["receivable_account_id"],
            revenue_account_id=payload["revenue_account_id"],
            currency=payload.get("currency", "GBP"),
            tax_code_id=payload.get("tax_code_id"),
        )
        return jsonify({
            "id": row.id,
            "status": row.status,
            "subtotal": str(row.subtotal),
            "tax_total": str(row.tax_total),
            "total": str(row.total),
            "journal_id": row.posted_journal_id,
        }), 201
    except (KeyError, ValueError, PermissionError, LedgerError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/payments")
@require_api("sales.read")
def payments():
    rows = SalesService.list_payments(g.access_context, min(int(request.args.get("limit", 100)), 500))
    return jsonify({"payments": [{
        "id": row.id,
        "customer_id": row.customer_id,
        "date": row.payment_date.isoformat(),
        "reference": row.reference,
        "amount": str(row.amount),
        "allocated": str(SalesService.payment_allocated(row.id)),
        "unallocated": str(row.amount - SalesService.payment_allocated(row.id)),
        "currency": row.currency,
        "status": row.status,
        "journal_id": row.journal_id,
    } for row in rows]})


@api_bp.post("/payments")
@require_api("sales.write")
def create_payment():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesService.record_payment(
            g.access_context,
            customer_id=payload["customer_id"],
            payment_date=date.fromisoformat(payload.get("date") or date.today().isoformat()),
            amount=payload["amount"],
            bank_account_id=payload["bank_account_id"],
            receivable_account_id=payload["receivable_account_id"],
            reference=payload.get("reference"),
            currency=payload.get("currency", "GBP"),
        )
        return jsonify({"id": row.id, "journal_id": row.journal_id, "status": row.status}), 201
    except (KeyError, ValueError, PermissionError, LedgerError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/payments/adopt-journal")
@require_api("sales.write")
def adopt_payment_journal():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesService.adopt_payment_journal(
            g.access_context,
            customer_id=payload["customer_id"],
            journal_id=payload["journal_id"],
            receivable_account_id=payload["receivable_account_id"],
            currency=payload.get("currency", "GBP"),
        )
        return jsonify({"id": row.id, "journal_id": row.journal_id, "amount": str(row.amount), "status": row.status}), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/payments/<payment_id>/allocate")
@require_api("sales.write")
def allocate_payment(payment_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesService.allocate_payment(g.access_context, payment_id, payload.get("allocations") or [])
        allocated = SalesService.payment_allocated(row.id)
        return jsonify({"id": row.id, "status": row.status, "allocated": str(allocated), "unallocated": str(row.amount - allocated)})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
