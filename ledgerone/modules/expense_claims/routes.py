from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ledgerone.module_registry import module_registry
from ledgerone.modules.expense_claims.services import ExpenseClaimError, ExpenseClaimService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerError, LedgerService

bp = Blueprint("expense_claims", __name__, url_prefix="/expense-claims")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("expense_claims")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                ExpenseClaimService.create_claim(
                    context,
                    claimant_name=request.form.get("claimant_name") or current_user.name,
                    claim_number=request.form.get("claim_number", ""),
                    claim_date=date.fromisoformat(request.form.get("claim_date") or date.today().isoformat()),
                    expense_date=date.fromisoformat(request.form.get("expense_date") or date.today().isoformat()),
                    merchant=request.form.get("merchant") or None,
                    description=request.form.get("description", "Expense"),
                    amount=request.form.get("amount", "0"),
                    expense_account_id=request.form.get("expense_account_id", ""),
                    reimbursement_account_id=request.form.get("reimbursement_account_id") or None,
                    currency=request.form.get("currency", "GBP"),
                    tax_code_id=request.form.get("tax_code_id") or None,
                )
                flash("Expense claim created as a draft.", "success")
            elif action == "add_line":
                ExpenseClaimService.add_line(
                    context,
                    request.form.get("claim_id", ""),
                    expense_date=date.fromisoformat(request.form.get("expense_date") or date.today().isoformat()),
                    merchant=request.form.get("merchant") or None,
                    description=request.form.get("description", "Expense"),
                    amount=request.form.get("amount", "0"),
                    expense_account_id=request.form.get("expense_account_id", ""),
                    tax_code_id=request.form.get("tax_code_id") or None,
                )
                flash("Expense line added.", "success")
            elif action == "submit":
                ExpenseClaimService.submit(context, request.form.get("claim_id", ""))
                flash("Expense claim submitted for approval.", "success")
            elif action == "approve":
                ExpenseClaimService.approve_and_post(
                    context,
                    request.form.get("claim_id", ""),
                    posting_date=date.fromisoformat(request.form.get("posting_date") or date.today().isoformat()),
                )
                flash("Expense claim approved and posted to the ledger.", "success")
            elif action == "reject":
                ExpenseClaimService.reject(
                    context,
                    request.form.get("claim_id", ""),
                    reason=request.form.get("reason") or None,
                )
                flash("Expense claim rejected.", "success")
            return redirect(url_for("expense_claims.index"))
        except (ExpenseClaimError, LedgerError, ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    tax_enabled = module_registry.is_enabled(context.organisation_id, "tax")
    tax_codes = []
    if tax_enabled and context.can("tax.read"):
        from ledgerone.modules.tax.services import TaxService
        tax_codes = TaxService.list_codes(context, usage="purchase")
    return render_template(
        "expense_claims/index.html",
        claims=ExpenseClaimService.list_claims(context, 150),
        expense_accounts=[row for row in accounts if row.account_type == "expense"],
        reimbursement_accounts=[row for row in accounts if row.account_type == "liability"],
        tax_enabled=tax_enabled,
        tax_codes=tax_codes,
        claimant_name=current_user.name,
        today=date.today().isoformat(),
    )
