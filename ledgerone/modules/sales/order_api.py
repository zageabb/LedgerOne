from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.sales.orders import SalesOrderService
from ledgerone.security import require_api

api_bp = Blueprint("sales_orders_api", __name__, url_prefix="/api/v1/sales/orders")


def _serialise(row):
    return {
        "id": row.id,
        "order_number": row.order_number,
        "customer_id": row.customer_id,
        "order_date": row.order_date.isoformat(),
        "requested_delivery_date": row.requested_delivery_date.isoformat() if row.requested_delivery_date else None,
        "currency": row.currency,
        "status": row.status,
        "subtotal": str(row.subtotal),
        "tax_total": str(row.tax_total),
        "total": str(row.total),
        "converted_invoice_id": row.converted_invoice_id,
        "lines": [
            {
                "id": line.id,
                "description": line.description,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "net_amount": str(line.net_amount),
                "tax_amount": str(line.tax_amount),
                "tax_code_id": line.tax_code_id,
                "revenue_account_id": line.revenue_account_id,
            }
            for line in row.lines
        ],
    }


@api_bp.get("")
@require_api("sales.read")
def list_orders():
    rows = SalesOrderService.list_orders(
        g.access_context, min(int(request.args.get("limit", 100)), 500)
    )
    return jsonify({"orders": [_serialise(row) for row in rows]})


@api_bp.post("")
@require_api("sales.write")
def create_order():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesOrderService.create_order(
            g.access_context,
            customer_id=payload["customer_id"],
            order_number=payload["order_number"],
            order_date=date.fromisoformat(payload.get("order_date") or date.today().isoformat()),
            requested_delivery_date=date.fromisoformat(payload["requested_delivery_date"]) if payload.get("requested_delivery_date") else None,
            description=payload.get("description", "Sales"),
            amount=payload["amount"],
            receivable_account_id=payload["receivable_account_id"],
            revenue_account_id=payload["revenue_account_id"],
            currency=payload.get("currency", "GBP"),
            tax_code_id=payload.get("tax_code_id"),
        )
        return jsonify(_serialise(row)), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<order_id>/status")
@require_api("sales.write")
def set_order_status(order_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesOrderService.set_status(
            g.access_context, order_id, status=payload.get("status", "draft")
        )
        return jsonify(_serialise(row))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<order_id>/convert")
@require_api("sales.write")
def convert_order(order_id):
    payload = request.get_json(silent=True) or {}
    try:
        invoice, order = SalesOrderService.convert_to_invoice(
            g.access_context,
            order_id,
            invoice_number=payload["invoice_number"],
            invoice_date=date.fromisoformat(payload.get("invoice_date") or date.today().isoformat()),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
        )
        return jsonify(
            {
                "order": _serialise(order),
                "invoice": {
                    "id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "status": invoice.status,
                    "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                    "subtotal": str(invoice.subtotal),
                    "tax_total": str(invoice.tax_total),
                    "total": str(invoice.total),
                    "journal_id": invoice.posted_journal_id,
                },
            }
        ), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
