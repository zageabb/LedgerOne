from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.sales.credits import SalesCreditService
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError

api_bp = Blueprint("sales_credits_api", __name__, url_prefix="/api/v1/sales/credit-notes")


@api_bp.get("")
@require_api("sales.read")
def list_credit_notes():
    rows = SalesCreditService.list_credit_notes(
        g.access_context, min(int(request.args.get("limit", 100)), 500)
    )
    return jsonify({"credit_notes": [
        {
            "id": row.id,
            "credit_number": row.credit_number,
            "invoice_id": row.invoice_id,
            "customer_id": row.customer_id,
            "credit_date": row.credit_date.isoformat(),
            "description": row.description,
            "currency": row.currency,
            "subtotal": str(row.subtotal),
            "tax_total": str(row.tax_total),
            "total": str(row.total),
            "status": row.status,
            "journal_id": row.posted_journal_id,
        }
        for row in rows
    ]})


@api_bp.post("")
@require_api("sales.write")
def create_credit_note():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesCreditService.create_credit_note(
            g.access_context,
            invoice_id=payload["invoice_id"],
            credit_number=payload.get("credit_number") or None,
            credit_date=date.fromisoformat(payload.get("credit_date") or date.today().isoformat()),
            amount=payload["amount"],
            description=payload.get("description"),
        )
        return jsonify({
            "id": row.id,
            "credit_number": row.credit_number,
            "subtotal": str(row.subtotal),
            "tax_total": str(row.tax_total),
            "total": str(row.total),
            "journal_id": row.posted_journal_id,
            "status": row.status,
        }), 201
    except (KeyError, ValueError, PermissionError, LedgerError) as exc:
        return jsonify({"error": str(exc)}), 400