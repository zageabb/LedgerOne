from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.modules.sales.credits import SalesCreditService
from ledgerone.modules.sales.services import SalesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError

bp = Blueprint("sales_credits", __name__, url_prefix="/sales/credit-notes")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("sales")
def index():
    context = browser_context()
    if request.method == "POST":
        try:
            SalesCreditService.create_credit_note(
                context,
                invoice_id=request.form.get("invoice_id", ""),
                credit_number=request.form.get("credit_number", ""),
                credit_date=date.fromisoformat(request.form.get("credit_date") or date.today().isoformat()),
                amount=request.form.get("amount", "0"),
                description=request.form.get("description") or None,
            )
            flash("Sales credit note created and posted.", "success")
            return redirect(url_for("sales_credits.index"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    invoices = SalesService.list_invoices(context, 250)
    outstanding = {row.id: SalesService.invoice_outstanding(row) for row in invoices}
    open_invoices = [row for row in invoices if outstanding[row.id] > 0]
    return render_template(
        "sales/credit_notes.html",
        credit_notes=SalesCreditService.list_credit_notes(context, 100),
        invoices=open_invoices,
        outstanding=outstanding,
        today=date.today().isoformat(),
    )
