from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError

api_bp = Blueprint("purchases_api", __name__, url_prefix="/api/v1/purchases")


@api_bp.get("/suppliers")
@require_api("purchases.read")
def suppliers():
    rows = PurchasesService.list_suppliers(g.access_context)
    return jsonify(
        {
            "suppliers": [
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


@api_bp.post("/suppliers")
@require_api("purchases.write")
def create_supplier():
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchasesService.create_supplier(
            g.access_context,
            name=payload.get("name", ""),
            email=payload.get("email"),
            phone=payload.get("phone"),
        )
        return jsonify({"id": row.id, "name": row.name}), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/bills")
@require_api("purchases.read")
def bills():
    rows = PurchasesService.list_bills(
        g.access_context, min(int(request.args.get("limit", 100)), 500)
    )
    return jsonify(
        {
            "bills": [
                {
                    "id": row.id,
                    "bill_number": row.bill_number,
                    "supplier_id": row.supplier_id,
                    "bill_date": row.bill_date.isoformat(),
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


@api_bp.post("/bills")
@require_api("purchases.write")
def create_bill():
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchasesService.create_bill(
            g.access_context,
            supplier_id=payload["supplier_id"],
            bill_number=payload["bill_number"],
            bill_date=date.fromisoformat(payload.get("bill_date") or date.today().isoformat()),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
            description=payload.get("description", "Purchase"),
            amount=payload["amount"],
            payable_account_id=payload["payable_account_id"],
            expense_account_id=payload["expense_account_id"],
            currency=payload.get("currency", "GBP"),
        )
        return jsonify({"id": row.id, "status": row.status, "journal_id": row.posted_journal_id}), 201
    except (KeyError, ValueError, PermissionError, LedgerError) as exc:
        return jsonify({"error": str(exc)}), 400
