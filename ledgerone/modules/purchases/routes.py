from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

bp = Blueprint("purchases", __name__, url_prefix="/purchases")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "supplier":
                PurchasesService.create_supplier(
                    context,
                    name=request.form.get("name", ""),
                    email=request.form.get("email"),
                    phone=request.form.get("phone"),
                )
                flash("Supplier added.", "success")
            elif action == "bill":
                bill_date = datetime.strptime(
                    request.form.get("bill_date") or date.today().isoformat(), "%Y-%m-%d"
                ).date()
                due_date_raw = request.form.get("due_date")
                due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None
                PurchasesService.create_bill(
                    context,
                    supplier_id=request.form.get("supplier_id", ""),
                    bill_number=request.form.get("bill_number", ""),
                    bill_date=bill_date,
                    due_date=due_date,
                    description=request.form.get("description", "Purchase"),
                    amount=request.form.get("amount", "0"),
                    payable_account_id=request.form.get("payable_account_id", ""),
                    expense_account_id=request.form.get("expense_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                )
                flash("Bill created and posted to the ledger.", "success")
            return redirect(url_for("purchases.index"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    return render_template(
        "purchases/index.html",
        suppliers=PurchasesService.list_suppliers(context),
        bills=PurchasesService.list_bills(context, 100),
        payable_accounts=[row for row in accounts if row.account_type == "liability"],
        expense_accounts=[row for row in accounts if row.account_type == "expense"],
        today=date.today().isoformat(),
        default_due=(date.today() + timedelta(days=30)).isoformat(),
    )
