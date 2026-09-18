from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.module_registry import module_registry
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError

api_bp = Blueprint("purchases_api", __name__, url_prefix="/api/v1/purchases")


@api_bp.get("/suppliers")
@require_api("purchases.read")
def suppliers():
    rows = PurchasesService.list_suppliers(g.access_context)
    return jsonify({"suppliers": [{"id": row.id, "name": row.name, "email": row.email, "phone": row.phone, "payment_terms_days": row.payment_terms_days, "is_active": row.is_active} for row in rows]})


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
            payment_terms_days=payload.get("payment_terms_days"),
        )
        return jsonify({"id": row.id, "name": row.name, "payment_terms_days": row.payment_terms_days}), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/bills")
@require_api("purchases.read")
def bills():
    rows = PurchasesService.list_bills(g.access_context, min(int(request.args.get("limit", 100)), 500))
    return jsonify({"bills": [{
        "id": row.id,
        "bill_number": row.bill_number,
        "supplier_id": row.supplier_id,
        "bill_date": row.bill_date.isoformat(),
        "tax_point": row.tax_point.isoformat(),
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "currency": row.currency,
        "status": row.status,
        "subtotal": str(row.subtotal),
        "tax_total": str(row.tax_total),
        "total": str(row.total),
        "tax_code_id": row.lines[0].tax_code_id if row.lines else None,
        "allocated": str(PurchasesService.bill_allocated(row.id)),
        "outstanding": str(PurchasesService.bill_outstanding(row)),
        "posted_journal_id": row.posted_journal_id,
    } for row in rows]})


@api_bp.post("/bills")
@require_api("purchases.write")
def create_bill():
    payload = request.get_json(silent=True) or {}
    try:
        bill_date = date.fromisoformat(payload.get("bill_date") or date.today().isoformat())
        due_date = date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None
        tax_point = date.fromisoformat(payload["tax_point"]) if payload.get("tax_point") else bill_date
        if module_registry.is_enabled(g.access_context.organisation_id, "workflows"):
            from ledgerone.modules.workflows.purchase_bill_requests import PurchaseBillWorkflowService

            workflow = PurchaseBillWorkflowService.create_request(
                g.access_context,
                supplier_id=payload["supplier_id"],
                bill_number=payload["bill_number"],
                bill_date=bill_date,
                due_date=due_date,
                tax_point=tax_point,
                description=payload.get("description", "Purchase"),
                amount=payload["amount"],
                payable_account_id=payload["payable_account_id"],
                expense_account_id=payload["expense_account_id"],
                currency=payload.get("currency", "GBP"),
                tax_code_id=payload.get("tax_code_id"),
                source_module="api",
                source_reference=payload.get("source_reference"),
                metadata={"created_by": "purchases_api"},
            )
            return jsonify({
                "workflow_instance_id": workflow.id,
                "status": workflow.status,
                "posted": False,
            }), 201

        row = PurchasesService.create_bill(
            g.access_context,
            supplier_id=payload["supplier_id"],
            bill_number=payload["bill_number"],
            bill_date=bill_date,
            due_date=due_date,
            tax_point=tax_point,
            description=payload.get("description", "Purchase"),
            amount=payload["amount"],
            payable_account_id=payload["payable_account_id"],
            expense_account_id=payload["expense_account_id"],
            currency=payload.get("currency", "GBP"),
            tax_code_id=payload.get("tax_code_id"),
        )
        return jsonify({
            "id": row.id,
            "status": row.status,
            "tax_point": row.tax_point.isoformat(),
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "subtotal": str(row.subtotal),
            "tax_total": str(row.tax_total),
            "total": str(row.total),
            "journal_id": row.posted_journal_id,
            "posted": True,
        }), 201
    except (KeyError, ValueError, PermissionError, LedgerError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/payments")
@require_api("purchases.read")
def payments():
    rows = PurchasesService.list_payments(g.access_context, min(int(request.args.get("limit", 100)), 500))
    return jsonify({"payments": [{
        "id": row.id,
        "supplier_id": row.supplier_id,
        "date": row.payment_date.isoformat(),
        "reference": row.reference,
        "amount": str(row.amount),
        "allocated": str(PurchasesService.payment_allocated(row.id)),
        "unallocated": str(row.amount - PurchasesService.payment_allocated(row.id)),
        "currency": row.currency,
        "status": row.status,
        "journal_id": row.journal_id,
    } for row in rows]})


@api_bp.post("/payments")
@require_api("purchases.write")
def create_payment():
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchasesService.record_payment(
            g.access_context,
            supplier_id=payload["supplier_id"],
            payment_date=date.fromisoformat(payload.get("date") or date.today().isoformat()),
            amount=payload["amount"],
            bank_account_id=payload["bank_account_id"],
            payable_account_id=payload["payable_account_id"],
            reference=payload.get("reference"),
            currency=payload.get("currency", "GBP"),
        )
        return jsonify({"id": row.id, "journal_id": row.journal_id, "status": row.status}), 201
    except (KeyError, ValueError, PermissionError, LedgerError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/payments/adopt-journal")
@require_api("purchases.write")
def adopt_payment_journal():
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchasesService.adopt_payment_journal(
            g.access_context,
            supplier_id=payload["supplier_id"],
            journal_id=payload["journal_id"],
            payable_account_id=payload["payable_account_id"],
            currency=payload.get("currency", "GBP"),
        )
        return jsonify({"id": row.id, "journal_id": row.journal_id, "amount": str(row.amount), "status": row.status}), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/payments/<payment_id>/allocate")
@require_api("purchases.write")
def allocate_payment(payment_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = PurchasesService.allocate_payment(g.access_context, payment_id, payload.get("allocations") or [])
        allocated = PurchasesService.payment_allocated(row.id)
        return jsonify({"id": row.id, "status": row.status, "allocated": str(allocated), "unallocated": str(row.amount - allocated)})
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
