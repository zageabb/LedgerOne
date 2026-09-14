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
    reversed_ids = {row.reversal_of_id for row in rows if row.reversal_of_id}
    return render_template(
        "ledger/journals.html",
        journals=rows,
        reversed_ids=reversed_ids,
        today=date.today().isoformat(),
    )


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


@bp.post("/journals/<journal_id>/reverse")
@login_required
@require_module("ledger")
def reverse_journal(journal_id):
    context = browser_context()
    try:
        reversal_date = date.fromisoformat(
            request.form.get("reversal_date") or date.today().isoformat()
        )
        reversal = LedgerService.reverse_journal(
            context,
            journal_id,
            reversal_date=reversal_date,
            reason=request.form.get("reason") or None,
        )
        flash(f"Journal reversed with {reversal.reference}.", "success")
    except (LedgerError, PermissionError, ValueError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ledger.journals"))


@bp.route("/periods", methods=["GET", "POST"])
@login_required
@require_module("ledger")
def periods():
    context = browser_context()
    if request.method == "POST":
        try:
            LedgerService.create_period(
                context,
                name=request.form.get("name", ""),
                start_date=date.fromisoformat(request.form.get("start_date", "")),
                end_date=date.fromisoformat(request.form.get("end_date", "")),
            )
            flash("Accounting period created.", "success")
            return redirect(url_for("ledger.periods"))
        except (LedgerError, PermissionError, ValueError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "ledger/periods.html",
        periods=LedgerService.list_periods(context),
    )


@bp.post("/periods/<period_id>/lock")
@login_required
@require_module("ledger")
def set_period_lock(period_id):
    context = browser_context()
    try:
        locked = request.form.get("locked") == "1"
        period = LedgerService.set_period_locked(context, period_id, locked=locked)
        flash(f"{period.name} is now {period.status}.", "success")
    except (LedgerError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ledger.periods"))


@bp.route("/opening-balances", methods=["GET", "POST"])
@login_required
@require_module("ledger")
def opening_balances():
    context = browser_context()
    accounts = [row for row in LedgerService.list_accounts(context) if row.is_active]
    equity_accounts = [row for row in accounts if row.account_type == "equity"]
    if request.method == "POST":
        entries = []
        for account in accounts:
            debit = request.form.get(f"debit_{account.id}", "").strip()
            credit = request.form.get(f"credit_{account.id}", "").strip()
            if not debit and not credit:
                continue
            entries.append(
                {
                    "account_id": account.id,
                    "description": "Opening balance",
                    "debit": debit or 0,
                    "credit": credit or 0,
                }
            )
        try:
            batch = LedgerService.create_opening_balance_batch(
                context,
                as_of_date=date.fromisoformat(request.form.get("as_of_date", "")),
                entries=entries,
                balancing_account_id=request.form.get("balancing_account_id") or None,
                reference=request.form.get("reference") or None,
                description=request.form.get("description") or "Opening balances",
            )
            flash(f"Opening balances posted as {batch.reference}.", "success")
            return redirect(url_for("ledger.opening_balances"))
        except (LedgerError, PermissionError, ValueError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "ledger/opening_balances.html",
        accounts=accounts,
        equity_accounts=equity_accounts,
        batches=LedgerService.list_opening_balance_batches(context),
        today=date.today().isoformat(),
    )


@bp.route("/recurring", methods=["GET", "POST"])
@login_required
@require_module("ledger")
def recurring_journals():
    context = browser_context()
    accounts = [row for row in LedgerService.list_accounts(context) if row.is_active]
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
            LedgerService.create_recurring_journal(
                context,
                name=request.form.get("name", ""),
                description=request.form.get("description", ""),
                reference=request.form.get("reference") or None,
                frequency=request.form.get("frequency", "monthly"),
                next_run_date=date.fromisoformat(request.form.get("next_run_date", "")),
                end_date=(
                    date.fromisoformat(request.form["end_date"])
                    if request.form.get("end_date") else None
                ),
                lines=lines,
            )
            flash("Recurring journal created.", "success")
            return redirect(url_for("ledger.recurring_journals"))
        except (LedgerError, PermissionError, ValueError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "ledger/recurring.html",
        accounts=accounts,
        recurring=LedgerService.list_recurring_journals(context),
        frequencies=LedgerService.RECURRING_FREQUENCIES,
        today=date.today().isoformat(),
    )


@bp.post("/recurring/<recurring_id>/run")
@login_required
@require_module("ledger")
def run_recurring_journal(recurring_id):
    context = browser_context()
    try:
        journal, _, schedule = LedgerService.run_recurring_journal(context, recurring_id)
        flash(
            f"Recurring journal posted as {journal.reference}. Next run: {schedule.next_run_date.isoformat()}.",
            "success",
        )
    except (LedgerError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ledger.recurring_journals"))


@bp.post("/recurring/<recurring_id>/active")
@login_required
@require_module("ledger")
def set_recurring_active(recurring_id):
    context = browser_context()
    try:
        row = LedgerService.set_recurring_journal_active(
            context,
            recurring_id,
            active=request.form.get("active") == "1",
        )
        flash(f"{row.name} is now {'active' if row.is_active else 'paused'}.", "success")
    except (LedgerError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("ledger.recurring_journals"))


@bp.get("/trial-balance")
@login_required
@require_module("ledger")
def trial_balance():
    context = browser_context()
    return render_template(
        "ledger/trial_balance.html",
        rows=LedgerService.trial_balance(context),
    )
