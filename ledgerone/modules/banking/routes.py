from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.modules.banking.services import BankingService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

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


@bp.get("/reconcile")
@login_required
@require_module("banking")
def reconcile():
    context = browser_context()
    unreconciled = BankingService.list_transactions(context, 200, status="unreconciled")
    reconciled = BankingService.list_transactions(context, 50, status="reconciled")
    selected_id = request.args.get("transaction_id") or (unreconciled[0].id if unreconciled else None)
    selected = next((row for row in unreconciled if row.id == selected_id), None)
    candidates = []
    candidate_error = None
    if selected:
        try:
            candidates = BankingService.reconciliation_candidates(context, selected.id)
        except (ValueError, PermissionError) as exc:
            candidate_error = str(exc)
    return render_template(
        "banking/reconcile.html",
        unreconciled=unreconciled,
        reconciled=reconciled,
        selected=selected,
        candidates=candidates,
        candidate_error=candidate_error,
        ledger_accounts=LedgerService.list_accounts(context),
    )


@bp.post("/transactions/<transaction_id>/match")
@login_required
@require_module("banking")
def match_transaction(transaction_id):
    context = browser_context()
    try:
        BankingService.match_transaction(
            context,
            transaction_id,
            request.form.get("journal_id", ""),
        )
        flash("Bank transaction matched to journal.", "success")
    except (ValueError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("banking.reconcile"))


@bp.post("/transactions/<transaction_id>/post-and-match")
@login_required
@require_module("banking")
def post_and_match(transaction_id):
    context = browser_context()
    try:
        _, journal = BankingService.post_and_match(
            context,
            transaction_id,
            offset_account_id=request.form.get("offset_account_id", ""),
            description=request.form.get("description") or None,
            reference=request.form.get("reference") or None,
        )
        flash(f"Bank transaction posted and reconciled as {journal.reference}.", "success")
    except (ValueError, LedgerError, PermissionError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("banking.reconcile", transaction_id=transaction_id))
    return redirect(url_for("banking.reconcile"))


@bp.post("/transactions/<transaction_id>/unmatch")
@login_required
@require_module("banking")
def unmatch_transaction(transaction_id):
    context = browser_context()
    try:
        BankingService.unmatch_transaction(context, transaction_id)
        flash("Bank transaction returned to unreconciled status.", "success")
    except (ValueError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("banking.reconcile"))


@bp.route("/statement-reconciliations", methods=["GET", "POST"])
@login_required
@require_module("banking")
def statement_reconciliations():
    context = browser_context()
    if request.method == "POST":
        try:
            row = BankingService.create_formal_reconciliation(
                context,
                bank_account_id=request.form["bank_account_id"],
                statement_start_date=date.fromisoformat(request.form["statement_start_date"]),
                statement_end_date=date.fromisoformat(request.form["statement_end_date"]),
                statement_opening_balance=request.form["statement_opening_balance"],
                statement_closing_balance=request.form["statement_closing_balance"],
                explained_difference=request.form.get("explained_difference") or 0,
                explanation=request.form.get("explanation"),
            )
            flash("Statement reconciliation prepared.", "success")
            return redirect(url_for("banking.statement_reconciliation_detail", reconciliation_id=row.id))
        except (KeyError, ValueError, PermissionError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "banking/statement_reconciliations.html",
        bank_accounts=BankingService.list_accounts(context),
        reconciliations=BankingService.list_formal_reconciliations(context),
    )


@bp.route("/statement-reconciliations/<reconciliation_id>", methods=["GET", "POST"])
@login_required
@require_module("banking")
def statement_reconciliation_detail(reconciliation_id):
    context = browser_context()
    try:
        if request.method == "POST":
            row = BankingService.refresh_formal_reconciliation(
                context,
                reconciliation_id,
                explained_difference=request.form.get("explained_difference"),
                explanation=request.form.get("explanation"),
            )
            flash("Reconciliation refreshed.", "success")
        else:
            row = BankingService.get_formal_reconciliation(context, reconciliation_id)
    except (ValueError, PermissionError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("banking.statement_reconciliations"))
    return render_template(
        "banking/statement_reconciliation_detail.html",
        reconciliation=row,
        evidence=BankingService.formal_reconciliation_evidence(context, row.id),
    )


@bp.post("/statement-reconciliations/<reconciliation_id>/finalise")
@login_required
@require_module("banking")
def finalise_statement_reconciliation(reconciliation_id):
    context = browser_context()
    try:
        BankingService.finalise_formal_reconciliation(context, reconciliation_id)
        flash("Statement reconciliation finalised and locked.", "success")
    except (ValueError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("banking.statement_reconciliation_detail", reconciliation_id=reconciliation_id))
