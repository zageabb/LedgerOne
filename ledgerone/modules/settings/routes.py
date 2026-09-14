from datetime import datetime, time, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required

from ledgerone.module_registry import module_registry
from ledgerone.modules.ai.configuration import AIConfiguration
from ledgerone.modules.settings.services import SettingsService
from ledgerone.security import browser_context
from ledgerone.services.payment_terms import PaymentTermsService

bp = Blueprint("settings", __name__, url_prefix="/settings")


def _ai_form_values():
    return {
        "enabled": request.form.get("ai_enabled") == "1",
        "base_url": request.form.get("ai_base_url", "").strip(),
        "model": request.form.get("ai_model", "").strip(),
        "timeout": int(request.form.get("ai_timeout", 120)),
        "allow_writes": request.form.get("ai_allow_writes") == "1",
    }


def _expiry_from_form(name: str = "expires_on"):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    day = datetime.strptime(raw, "%Y-%m-%d").date()
    return datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    context = browser_context()

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "general":
                SettingsService.update_organisation(
                    context,
                    name=request.form.get("name", ""),
                    base_currency=request.form.get("base_currency", "GBP"),
                    country_code=request.form.get("country_code", "GB"),
                    fiscal_year_start_month=int(request.form.get("fiscal_year_start_month", 4)),
                    fiscal_year_start_day=int(request.form.get("fiscal_year_start_day", 1)),
                )
                flash("Organisation settings updated.", "success")
            elif action == "payment_terms":
                PaymentTermsService.update(
                    context,
                    customer_days=request.form.get("customer_payment_terms_days", 30),
                    supplier_days=request.form.get("supplier_payment_terms_days", 30),
                )
                flash("Default payment terms updated.", "success")
            elif action == "module":
                module_id = request.form.get("module_id", "")
                enabled = request.form.get("enabled") == "1"
                SettingsService.set_module_enabled(context, module_id, enabled)
                if enabled:
                    module_registry.seed_module_defaults(context.organisation_id, module_id)
                flash("Module setting updated.", "success")
            elif action == "member_save":
                SettingsService.save_member(
                    context,
                    email=request.form.get("member_email", ""),
                    name=request.form.get("member_name", ""),
                    role=request.form.get("member_role", "member"),
                    permissions=request.form.getlist("member_permissions"),
                    password=request.form.get("member_password") or None,
                    active=request.form.get("member_active", "1") == "1",
                )
                flash("Member access updated.", "success")
            elif action == "member_deactivate":
                SettingsService.deactivate_member(
                    context,
                    request.form.get("membership_id", ""),
                )
                flash("Member deactivated.", "success")
            elif action == "ai_save":
                values = _ai_form_values()
                AIConfiguration.update(context, **values)
                flash("AI settings updated. Changes take effect immediately.", "success")
            elif action == "ai_test":
                if not context.can("settings.manage"):
                    raise PermissionError("settings.manage")
                values = _ai_form_values()
                base_url, model, timeout = AIConfiguration._validate(
                    base_url=values["base_url"],
                    model=values["model"],
                    timeout=values["timeout"],
                )
                values.update({"base_url": base_url, "model": model, "timeout": timeout})
                session["ai_test_values"] = values
                result = AIConfiguration.probe(base_url=base_url, timeout=3)
                session["ai_test_result"] = result
                if result["reachable"]:
                    flash(
                        f"AI server connected successfully. {len(result.get('models', []))} model(s) found.",
                        "success",
                    )
                else:
                    flash(f"AI server connection failed: {result.get('error', 'Unknown error')}", "danger")
            elif action == "api_key":
                permissions = [
                    item.strip()
                    for item in request.form.get("permissions", "").split(",")
                    if item.strip()
                ]
                _, token = SettingsService.issue_api_key(
                    context,
                    name=request.form.get("key_name", "API key"),
                    full_access=request.form.get("full_access") == "1",
                    permissions=permissions,
                    expires_at=_expiry_from_form(),
                )
                session["new_api_token"] = token
                flash("API key created. Copy it now; it will not be shown again.", "success")
            elif action == "rotate_api_key":
                _, token = SettingsService.rotate_api_key(
                    context,
                    request.form.get("key_id", ""),
                    expires_at=_expiry_from_form("rotate_expires_on"),
                )
                session["new_api_token"] = token
                flash("API key rotated. The previous key was revoked; copy the replacement now.", "success")
            elif action == "revoke_api_key":
                SettingsService.revoke_api_key(context, request.form.get("key_id", ""))
                flash("API key revoked.", "success")
            return redirect(url_for("settings.index"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    ai_settings = session.pop("ai_test_values", None) or AIConfiguration.get(context.organisation_id)
    ai_probe = session.pop("ai_test_result", None)
    if ai_probe is None:
        ai_probe = AIConfiguration.probe(base_url=ai_settings["base_url"], timeout=3)

    return render_template(
        "settings/index.html",
        organisation=SettingsService.organisation(context),
        payment_terms=PaymentTermsService.get(context.organisation_id),
        module_states=SettingsService.module_states(context),
        members=SettingsService.list_members(context),
        permission_catalog=SettingsService.permission_catalog(),
        api_keys=SettingsService.list_api_keys(context),
        new_api_token=session.pop("new_api_token", None),
        ai_settings=ai_settings,
        ai_probe=ai_probe,
    )


@bp.route("/payment-terms", methods=["GET", "POST"])
@login_required
def payment_terms():
    context = browser_context()
    if request.method == "POST":
        try:
            PaymentTermsService.update(
                context,
                customer_days=request.form.get("customer_days", 30),
                supplier_days=request.form.get("supplier_days", 30),
            )
            flash("Default payment terms updated.", "success")
            return redirect(url_for("settings.payment_terms"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "settings/payment_terms.html",
        payment_terms=PaymentTermsService.get(context.organisation_id),
    )