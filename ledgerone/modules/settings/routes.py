from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required

from ledgerone.modules.settings.services import SettingsService
from ledgerone.security import browser_context

bp = Blueprint("settings", __name__, url_prefix="/settings")


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
            elif action == "module":
                SettingsService.set_module_enabled(
                    context,
                    request.form.get("module_id", ""),
                    request.form.get("enabled") == "1",
                )
                flash("Module setting updated.", "success")
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
                )
                session["new_api_token"] = token
                flash("API key created. Copy it now; it will not be shown again.", "success")
            elif action == "revoke_api_key":
                SettingsService.revoke_api_key(context, request.form.get("key_id", ""))
                flash("API key revoked.", "success")
            return redirect(url_for("settings.index"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    return render_template(
        "settings/index.html",
        organisation=SettingsService.organisation(context),
        module_states=SettingsService.module_states(context),
        api_keys=SettingsService.list_api_keys(context),
        new_api_token=session.pop("new_api_token", None),
    )
