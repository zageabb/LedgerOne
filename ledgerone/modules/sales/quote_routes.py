from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.module_registry import module_registry
from ledgerone.modules.sales.quotes import SalesQuoteService
from ledgerone.modules.sales.services import SalesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerService

bp = Blueprint("sales_quotes", __name__, url_prefix="/sales/quotes")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("sales")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                SalesQuoteService.create_quote(
                    context,
                    customer_id=request.form.get("customer_id", ""),
                    quote_number=request.form.get("quote_number", ""),
                    quote_date=date.fromisoformat(request.form.get("quote_date") or date.today().isoformat()),
                    expiry_date=date.fromisoformat(request.form["expiry_date"]) if request.form.get("expiry_date") else None,
                    description=request.form.get("description", "Sales"),
                    amount=request.form.get("amount", "0"),
                    receivable_account_id=request.form.get("receivable_account_id", ""),
                    revenue_account_id=request.form.get("revenue_account_id", ""),
                    currency=request.form.get("currency", "GBP"),
                    tax_code_id=request.form.get("tax_code_id") or None,
                )
                flash("Quote created. No ledger posting has been made.", "success")
            elif action == "status":
                SalesQuoteService.set_status(
                    context,
                    request.form.get("quote_id", ""),
                    status=request.form.get("status", "draft"),
                )
                flash("Quote status updated.", "success")
            elif action == "convert":
                invoice, _ = SalesQuoteService.convert_to_invoice(
                    context,
                    request.form.get("quote_id", ""),
                    invoice_number=request.form.get("invoice_number", ""),
                    invoice_date=date.fromisoformat(request.form.get("invoice_date") or date.today().isoformat()),
                    due_date=date.fromisoformat(request.form["due_date"]) if request.form.get("due_date") else None,
                )
                flash(f"Quote converted to invoice {invoice.invoice_number} and posted.", "success")
            return redirect(url_for("sales_quotes.index"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    tax_codes = []
    tax_enabled = module_registry.is_enabled(context.organisation_id, "tax")
    if tax_enabled and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage="sales")
    return render_template(
        "sales/quotes.html",
        quotes=SalesQuoteService.list_quotes(context, 150),
        customers=SalesService.list_customers(context),
        receivable_accounts=[row for row in accounts if row.account_type == "asset"],
        revenue_accounts=[row for row in accounts if row.account_type == "income"],
        tax_codes=tax_codes,
        tax_enabled=tax_enabled,
        today=date.today().isoformat(),
        default_expiry=(date.today() + timedelta(days=30)).isoformat(),
        default_due="",
    )
