from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.purchases.credits import PurchaseCreditService
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError

api_bp = Blueprint("purchase_credits_api", __name__, url_prefix="/api/v1/purchases/credit-notes")


@api_bp.get("")
@require_api("purchases.read")
def list_credit_notes():
    rows = PurchaseCreditService.list_credit_notes(
        g.access_context, min(int(request.args.get("limit", 100)), 500)
    )
    return jsonify({"credit_notes": [
        {
            "id": row.id,
            "credit_number": row.credit_number,
            "bill_id": row.bill_id,
            "supplier_id": row.supplier_id,
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
@require_api("purchases.write")
def create_credit_note():
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchaseCreditService.create_credit_note(
            g.access_context,
            bill_id=payload["bill_id"],
            credit_number=payload["credit_number"],
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
