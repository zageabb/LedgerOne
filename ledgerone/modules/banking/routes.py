from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerService
from ledgerone.modules.banking.services import BankingService

bp = Blueprint("banking", __name__, url_prefix="/banking")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("banking")
def index():
    context = browser_context()
    if request.method == "POST":
        try:
            BankingService.create_account(
                context,
                name=request.form.get("name", "Bank account"),
                institution=request.form.get("institution"),
                currency=request.form.get("currency", "GBP"),
                ledger_account_id=request.form.get("ledger_account_id") or None,
            )
            flash("Bank account added.", "success")
            return redirect(url_for("banking.index"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    return render_template(
        "banking/index.html",
        bank_accounts=BankingService.list_accounts(context),
        transactions=BankingService.list_transactions(context, 50),
        ledger_accounts=LedgerService.list_accounts(context),
    )
