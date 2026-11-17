from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.module_registry import module_registry
from ledgerone.modules.commercial.models import CommercialDocument
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.sales.orders import SalesOrderService
from ledgerone.modules.sales.services import SalesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

bp = Blueprint("sales_orders", __name__, url_prefix="/sales/orders")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("sales")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                SalesOrderService.create_order(
                    context,
                    customer_id=request.form.get("customer_id", ""),
                    order_number=request.form.get("order_number", ""),
                    order_date=date.fromisoformat(request.form.get("order_date") or date.today().isoformat()),
                    requested_delivery_date=date.fromisoformat(request.form["requested_delivery_date"]) if request.form.get("requested_delivery_date") else None,
                    description=request.form.get("description", "Sales"),
                    amount=request.form.get("amount", "0"),
                    receivable_account_id=request.form.get("receivable_account_id", ""),
                    revenue_account_id=request.form.get("revenue_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                    tax_code_id=request.form.get("tax_code_id") or None,
                )
                flash("Sales order created. No ledger posting has been made.", "success")
            elif action == "status":
                SalesOrderService.set_status(
                    context,
                    request.form.get("order_id", ""),
                    status=request.form.get("status", "draft"),
                )
                flash("Sales order status updated.", "success")
            elif action in {"so_ack", "delivery_note"}:
                doc_type = action
                document_lines = None
                if doc_type == "delivery_note":
                    document_lines = [{
                        "order_line_id": request.form.get("order_line_id", ""),
                        "quantity": request.form.get("quantity", ""),
                    }]
                document = CommercialDocumentService.create(
                    context, document_type=doc_type,
                    order_id=request.form.get("order_id", ""),
                    document_date=date.fromisoformat(
                        request.form.get("document_date") or date.today().isoformat()),
                    lines=document_lines)
                flash(f"{document.document_number} recorded without posting a journal.", "success")
            elif action == "convert":
                invoice, _ = SalesOrderService.convert_to_invoice(
                    context,
                    request.form.get("order_id", ""),
                    invoice_number=request.form.get("invoice_number", ""),
                    invoice_date=date.fromisoformat(request.form.get("invoice_date") or date.today().isoformat()),
                    due_date=date.fromisoformat(request.form["due_date"]) if request.form.get("due_date") else None,
                )
                flash(f"Sales order converted to invoice {invoice.invoice_number} and posted.", "success")
            return redirect(url_for("sales_orders.index"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    tax_codes = []
    tax_enabled = module_registry.is_enabled(context.organisation_id, "tax")
    if tax_enabled and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage="sales")
    document_records = CommercialDocument.query.filter(
        CommercialDocument.organisation_id == context.organisation_id,
        CommercialDocument.document_type.in_(["so_ack","delivery_note"]),
    ).order_by(CommercialDocument.created_at.desc()).limit(500).all()
    order_documents = {}
    for document in document_records:
        order_documents.setdefault(document.order_id, []).append(document)
    return render_template(
        "sales/orders.html",
        order_documents=order_documents,
        orders=SalesOrderService.list_orders(context, 150),
        customers=SalesService.list_customers(context),
        receivable_accounts=[row for row in accounts if row.account_type == "asset"],
        revenue_accounts=[row for row in accounts if row.account_type == "income"],
        tax_codes=tax_codes,
        tax_enabled=tax_enabled,
        today=date.today().isoformat(),
        default_delivery=(date.today() + timedelta(days=14)).isoformat(),
        default_due="",
    )
