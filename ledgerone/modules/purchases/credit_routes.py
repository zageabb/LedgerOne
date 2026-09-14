from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.modules.purchases.credits import PurchaseCreditService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError

bp = Blueprint("purchase_credits", __name__, url_prefix="/purchases/credit-notes")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("purchases")
def index():
    context = browser_context()
    if request.method == "POST":
        try:
            PurchaseCreditService.create_credit_note(
                context,
                bill_id=request.form.get("bill_id", ""),
                credit_number=request.form.get("credit_number", ""),
                credit_date=date.fromisoformat(request.form.get("credit_date") or date.today().isoformat()),
                amount=request.form.get("amount", "0"),
                description=request.form.get("description") or None,
            )
            flash("Purchase credit note created and posted.", "success")
            return redirect(url_for("purchase_credits.index"))
        except (ValueError, PermissionError, LedgerError) as exc:
            flash(str(exc), "danger")

    bills = PurchasesService.list_bills(context, 250)
    outstanding = {row.id: PurchasesService.bill_outstanding(row) for row in bills}
    open_bills = [row for row in bills if outstanding[row.id] > 0]
    return render_template(
        "purchases/credit_notes.html",
        credit_notes=PurchaseCreditService.list_credit_notes(context, 100),
        bills=open_bills,
        outstanding=outstanding,
        today=date.today().isoformat(),
    )
