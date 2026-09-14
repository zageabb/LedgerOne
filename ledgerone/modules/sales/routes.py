from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.modules.sales.services import SalesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

bp = Blueprint("sales", __name__, url_prefix="/sales")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("sales")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "customer":
                SalesService.create_customer(
                    context,
                    name=request.form.get("name", ""),
                    email=request.form.get("email"),
                    phone=request.form.get("phone"),
                )
                flash("Customer added.", "success")
            elif action == "invoice":
                invoice_date = datetime.strptime(
                    request.form.get("invoice_date") or date.today().isoformat(), "%Y-%m-%d"
                ).date()
                due_date_raw = request.form.get("due_date")
                due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None
                SalesService.create_invoice(
                    context,
                    customer_id=request.form.get("customer_id", ""),
                    invoice_number=request.form.get("invoice_number", ""),
                    invoice_date=invoice_date,
                    due_date=due_date,
                    description=request.form.get("description", "Sales"),
                    amount=request.form.get("amount", "0"),
                    receivable_account_id=request.form.get("receivable_account_id", ""),
                    revenue_account_id=request.form.get("revenue_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                )
                flash("Invoice created and posted to the ledger.", "success")
            return redirect(url_for("sales.index"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    return render_template(
        "sales/index.html",
        customers=SalesService.list_customers(context),
        invoices=SalesService.list_invoices(context, 100),
        receivable_accounts=[row for row in accounts if row.account_type == "asset"],
        revenue_accounts=[row for row in accounts if row.account_type == "income"],
        today=date.today().isoformat(),
        default_due=(date.today() + timedelta(days=30)).isoformat(),
    )
