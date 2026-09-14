from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.module_registry import module_registry
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerService

bp = Blueprint("purchase_orders", __name__, url_prefix="/purchases/orders")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                PurchaseOrderService.create_order(
                    context,
                    supplier_id=request.form.get("supplier_id", ""),
                    order_number=request.form.get("order_number", ""),
                    order_date=date.fromisoformat(request.form.get("order_date") or date.today().isoformat()),
                    expected_date=date.fromisoformat(request.form["expected_date"]) if request.form.get("expected_date") else None,
                    description=request.form.get("description", "Purchase"),
                    amount=request.form.get("amount", "0"),
                    payable_account_id=request.form.get("payable_account_id", ""),
                    expense_account_id=request.form.get("expense_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                    tax_code_id=request.form.get("tax_code_id") or None,
                )
                flash("Purchase order created. No ledger posting has been made.", "success")
            elif action == "status":
                PurchaseOrderService.set_status(
                    context,
                    request.form.get("order_id", ""),
                    status=request.form.get("status", "draft"),
                )
                flash("Purchase order status updated.", "success")
            elif action == "convert":
                bill, _ = PurchaseOrderService.convert_to_bill(
                    context,
                    request.form.get("order_id", ""),
                    bill_number=request.form.get("bill_number", ""),
                    bill_date=date.fromisoformat(request.form.get("bill_date") or date.today().isoformat()),
                    due_date=date.fromisoformat(request.form["due_date"]) if request.form.get("due_date") else None,
                )
                flash(f"Purchase order converted to bill {bill.bill_number} and posted.", "success")
            return redirect(url_for("purchase_orders.index"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    tax_codes = []
    tax_enabled = module_registry.is_enabled(context.organisation_id, "tax")
    if tax_enabled and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage="purchase")
    return render_template(
        "purchases/orders.html",
        orders=PurchaseOrderService.list_orders(context, 150),
        suppliers=PurchasesService.list_suppliers(context),
        payable_accounts=[row for row in accounts if row.account_type == "liability"],
        expense_accounts=[row for row in accounts if row.account_type == "expense"],
        tax_codes=tax_codes,
        tax_enabled=tax_enabled,
        today=date.today().isoformat(),
        default_expected=(date.today() + timedelta(days=14)).isoformat(),
        default_due="",
    )
