from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.modules.tax.services import TaxError, TaxService
from ledgerone.security import browser_context, require_module
from ledgerone.services.ledger import LedgerService

bp = Blueprint("tax", __name__, url_prefix="/tax")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("tax")
def index():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "profile":
                TaxService.update_profile(
                    context,
                    jurisdiction=request.form.get("jurisdiction", "GB"),
                    is_vat_registered=request.form.get("is_vat_registered") == "1",
                    registration_number=request.form.get("registration_number"),
                    scheme=request.form.get("scheme", "standard"),
                    return_frequency=request.form.get("return_frequency", "quarterly"),
                )
                flash("Tax profile updated.", "success")
            elif action == "code":
                TaxService.create_code(
                    context,
                    code=request.form.get("code", ""),
                    name=request.form.get("name", ""),
                    rate_percent=request.form.get("rate_percent", "0"),
                    treatment=request.form.get("treatment", "standard"),
                    scope=request.form.get("scope", "both"),
                    sales_tax_account_id=request.form.get("sales_tax_account_id") or None,
                    purchase_tax_account_id=request.form.get("purchase_tax_account_id") or None,
                )
                flash("Tax code created.", "success")
        except (TaxError, ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    accounts = LedgerService.list_accounts(context)
    return render_template(
        "tax/index.html",
        profile=TaxService.profile(context),
        tax_codes=TaxService.list_codes(context, active_only=False),
        liability_accounts=[row for row in accounts if row.account_type == "liability"],
        asset_accounts=[row for row in accounts if row.account_type == "asset"],
    )


@bp.get("/vat-return")
@login_required
@require_module("tax")
def vat_return():
    context = browser_context()
    today = date.today()
    start_raw = request.args.get("from_date") or today.replace(day=1).isoformat()
    end_raw = request.args.get("to_date") or today.isoformat()
    try:
        start_date = date.fromisoformat(start_raw)
        end_date = date.fromisoformat(end_raw)
        summary = TaxService.vat_return(context, start_date=start_date, end_date=end_date)
    except (TaxError, ValueError, PermissionError) as exc:
        flash(str(exc), "danger")
        start_date = today.replace(day=1)
        end_date = today
        summary = TaxService.vat_return(context, start_date=start_date, end_date=end_date)
    return render_template(
        "tax/vat_return.html",
        summary=summary,
        from_date=start_date.isoformat(),
        to_date=end_date.isoformat(),
    )


@bp.route("/vat-returns", methods=["GET", "POST"])
@login_required
@require_module("tax")
def vat_returns():
    context = browser_context()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create_period":
                TaxService.create_return_period(
                    context,
                    start_date=date.fromisoformat(request.form["start_date"]),
                    end_date=date.fromisoformat(request.form["end_date"]),
                )
                flash("Draft VAT return period created.", "success")
            elif action == "adjustment":
                TaxService.create_adjustment(
                    context,
                    tax_point=date.fromisoformat(request.form["tax_point"]),
                    box_number=request.form.get("box_number", ""),
                    amount=request.form.get("amount", "0"),
                    reason=request.form.get("reason", ""),
                    evidence_reference=request.form.get("evidence_reference"),
                )
                flash("VAT adjustment recorded.", "success")
            elif action == "finalise":
                TaxService.finalise_return_period(context, request.form.get("period_id", ""))
                flash("VAT return finalised and source population frozen.", "success")
            elif action == "submit":
                TaxService.mark_return_submitted(
                    context,
                    request.form.get("period_id", ""),
                    submission_reference=request.form.get("submission_reference", ""),
                    submission_note=request.form.get("submission_note"),
                )
                flash("VAT return marked submitted.", "success")
            return redirect(url_for("tax.vat_returns"))
        except (KeyError, TaxError, ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    periods = TaxService.list_return_periods(context)
    summaries = {}
    for period in periods:
        try:
            summaries[period.id] = TaxService.return_period_summary(context, period.id)
        except (TaxError, ValueError, PermissionError):
            summaries[period.id] = None
    return render_template(
        "tax/vat_returns.html",
        periods=periods,
        summaries=summaries,
        adjustments=TaxService.list_adjustments(context),
        today=date.today().isoformat(),
    )
