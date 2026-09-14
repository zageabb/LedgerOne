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
    return jsonify(
        {
            "customers": [
                {
                    "id": row.id,
                    "name": row.name,
                    "email": row.email,
                    "phone": row.phone,
                    "is_active": row.is_active,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/customers")
@require_api("sales.write")
def create_customer():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesService.create_customer(
            g.access_context,
            name=payload.get("name", ""),
            email=payload.get("email"),
            phone=payload.get("phone"),
        )
        return jsonify({"id": row.id, "name": row.name}), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/invoices")
@require_api("sales.read")
def invoices():
    rows = SalesService.list_invoices(
        g.access_context, min(int(request.args.get("limit", 100)), 500)
    )
    return jsonify(
        {
            "invoices": [
                {
                    "id": row.id,
                    "invoice_number": row.invoice_number,
                    "customer_id": row.customer_id,
                    "invoice_date": row.invoice_date.isoformat(),
                    "due_date": row.due_date.isoformat() if row.due_date else None,
                    "currency": row.currency,
                    "status": row.status,
                    "total": str(row.total),
                    "posted_journal_id": row.posted_journal_id,
                }
                for row in rows
            ]
        }
    )


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
        )
        return jsonify({"id": row.id, "status": row.status, "journal_id": row.posted_journal_id}), 201
    except (KeyError, ValueError, PermissionError, LedgerError) as exc:
        return jsonify({"error": str(exc)}), 400
