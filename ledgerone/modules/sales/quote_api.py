from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.sales.quotes import SalesQuoteService
from ledgerone.security import require_api

api_bp = Blueprint("sales_quotes_api", __name__, url_prefix="/api/v1/sales/quotes")


def _serialise(row):
    return {
        "id": row.id,
        "quote_number": row.quote_number,
        "customer_id": row.customer_id,
        "quote_date": row.quote_date.isoformat(),
        "expiry_date": row.expiry_date.isoformat() if row.expiry_date else None,
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
def list_quotes():
    rows = SalesQuoteService.list_quotes(
        g.access_context, min(int(request.args.get("limit", 100)), 500)
    )
    return jsonify({"quotes": [_serialise(row) for row in rows]})


@api_bp.post("")
@require_api("sales.write")
def create_quote():
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesQuoteService.create_quote(
            g.access_context,
            customer_id=payload["customer_id"],
            quote_number=payload["quote_number"],
            quote_date=date.fromisoformat(payload.get("quote_date") or date.today().isoformat()),
            expiry_date=date.fromisoformat(payload["expiry_date"]) if payload.get("expiry_date") else None,
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


@api_bp.post("/<quote_id>/status")
@require_api("sales.write")
def set_quote_status(quote_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = SalesQuoteService.set_status(
            g.access_context, quote_id, status=payload.get("status", "draft")
        )
        return jsonify(_serialise(row))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<quote_id>/convert")
@require_api("sales.write")
def convert_quote(quote_id):
    payload = request.get_json(silent=True) or {}
    try:
        invoice, quote = SalesQuoteService.convert_to_invoice(
            g.access_context,
            quote_id,
            invoice_number=payload["invoice_number"],
            invoice_date=date.fromisoformat(payload.get("invoice_date") or date.today().isoformat()),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
        )
        return jsonify(
            {
                "quote": _serialise(quote),
                "invoice": {
                    "id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "status": invoice.status,
                    "subtotal": str(invoice.subtotal),
                    "tax_total": str(invoice.tax_total),
                    "total": str(invoice.total),
                    "journal_id": invoice.posted_journal_id,
                },
            }
        ), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
