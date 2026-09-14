from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.models.ledger import Journal
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

bp = Blueprint("ledger", __name__, url_prefix="/ledger")


@bp.route("/accounts", methods=["GET", "POST"])
@login_required
@require_module("ledger")
def accounts():
    context = browser_context()
    if request.method == "POST":
        try:
            LedgerService.create_account(
                context,
                code=request.form.get("code", ""),
                name=request.form.get("name", ""),
                account_type=request.form.get("account_type", "expense"),
                currency=request.form.get("currency") or None,
                parent_id=request.form.get("parent_id") or None,
            )
            flash("Account created.", "success")
            return redirect(url_for("ledger.accounts"))
        except (LedgerError, PermissionError) as exc:
            flash(str(exc), "danger")
    return render_template("ledger/accounts.html", accounts=LedgerService.list_accounts(context))


@bp.get("/journals")
@login_required
@require_module("ledger")
def journals():
    context = browser_context()
    rows = (
        Journal.query.filter_by(organisation_id=context.organisation_id)
        .order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template("ledger/journals.html", journals=rows)


@bp.route("/journals/new", methods=["GET", "POST"])
@login_required
@require_module("ledger")
def new_journal():
    context = browser_context()
    accounts = LedgerService.list_accounts(context)

    if request.method == "POST":
        lines = []
        for index in range(1, 7):
            account_id = request.form.get(f"line_{index}_account")
            debit = request.form.get(f"line_{index}_debit", "").strip()
            credit = request.form.get(f"line_{index}_credit", "").strip()
            if not account_id and not debit and not credit:
                continue
            lines.append(
                {
                    "account_id": account_id,
                    "description": request.form.get(f"line_{index}_description") or None,
                    "debit": debit or 0,
                    "credit": credit or 0,
                    "dimensions": {},
                }
            )
        try:
            journal_date = datetime.strptime(
                request.form.get("journal_date") or date.today().isoformat(), "%Y-%m-%d"
            ).date()
            LedgerService.post_journal(
                context,
                journal_date=journal_date,
                description=request.form.get("description", "Manual journal"),
                reference=request.form.get("reference") or None,
                lines=lines,
                source_module="ledger",
            )
            flash("Journal posted.", "success")
            return redirect(url_for("ledger.journals"))
        except (LedgerError, PermissionError, ValueError) as exc:
            flash(str(exc), "danger")

    return render_template(
        "ledger/new_journal.html",
        accounts=accounts,
        today=date.today().isoformat(),
    )


@bp.get("/trial-balance")
@login_required
@require_module("ledger")
def trial_balance():
    context = browser_context()
    return render_template(
        "ledger/trial_balance.html",
        rows=LedgerService.trial_balance(context),
    )
