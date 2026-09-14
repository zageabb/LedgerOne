from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.security import require_api

api_bp = Blueprint("purchase_orders_api", __name__, url_prefix="/api/v1/purchases/orders")


def _serialise(row):
    return {
        "id": row.id,
        "order_number": row.order_number,
        "supplier_id": row.supplier_id,
        "order_date": row.order_date.isoformat(),
        "expected_date": row.expected_date.isoformat() if row.expected_date else None,
        "currency": row.currency,
        "status": row.status,
        "subtotal": str(row.subtotal),
        "tax_total": str(row.tax_total),
        "total": str(row.total),
        "converted_bill_id": row.converted_bill_id,
        "lines": [
            {
                "id": line.id,
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "net_amount": str(line.net_amount),
                "tax_amount": str(line.tax_amount),
                "tax_code_id": line.tax_code_id,
                "expense_account_id": line.expense_account_id,
            }
            for line in row.lines
        ],
    }


@api_bp.get("")
@require_api("purchases.read")
def list_orders():
    rows = PurchaseOrderService.list_orders(
        g.access_context, min(int(request.args.get("limit", 100)), 500)
    )
    return jsonify({"orders": [_serialise(row) for row in rows]})


@api_bp.post("")
@require_api("purchases.write")
def create_order():
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchaseOrderService.create_order(
            g.access_context,
            supplier_id=payload["supplier_id"],
            order_number=payload["order_number"],
            order_date=date.fromisoformat(payload.get("order_date") or date.today().isoformat()),
            expected_date=date.fromisoformat(payload["expected_date"]) if payload.get("expected_date") else None,
            description=payload.get("description", "Purchase"),
            amount=payload["amount"],
            payable_account_id=payload["payable_account_id"],
            expense_account_id=payload["expense_account_id"],
            currency=payload.get("currency", "GBP"),
            tax_code_id=payload.get("tax_code_id"),
        )
        return jsonify(_serialise(row)), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<order_id>/status")
@require_api("purchases.write")
def set_order_status(order_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchaseOrderService.set_status(
            g.access_context, order_id, status=payload.get("status", "draft")
        )
        return jsonify(_serialise(row))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<order_id>/convert")
@require_api("purchases.write")
def convert_order(order_id):
    payload = request.get_json(silent=True) or {}
    try:
        bill, order = PurchaseOrderService.convert_to_bill(
            g.access_context,
            order_id,
            bill_number=payload["bill_number"],
            bill_date=date.fromisoformat(payload.get("bill_date") or date.today().isoformat()),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
        )
        return jsonify(
            {
                "order": _serialise(order),
                "bill": {
                    "id": bill.id,
                    "bill_number": bill.bill_number,
                    "status": bill.status,
                    "subtotal": str(bill.subtotal),
                    "tax_total": str(bill.tax_total),
                    "total": str(bill.total),
                    "journal_id": bill.posted_journal_id,
                },
            }
        ), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
