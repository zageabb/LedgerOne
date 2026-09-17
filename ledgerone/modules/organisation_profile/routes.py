from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.security import browser_context, require_browser_permission

from .services import OrganisationProfileService


bp = Blueprint("organisation_profile", __name__, url_prefix="/business-profile")


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_browser_permission("settings.read")
def index():
    context = browser_context()
    if request.method == "POST":
        try:
            OrganisationProfileService.update(
                context,
                registered_name=request.form.get("registered_name", ""),
                trading_name=request.form.get("trading_name"),
                company_number=request.form.get("company_number"),
                email=request.form.get("email"),
                phone=request.form.get("phone"),
                website=request.form.get("website"),
                address_line1=request.form.get("address_line1"),
                address_line2=request.form.get("address_line2"),
                city=request.form.get("city"),
                county=request.form.get("county"),
                postcode=request.form.get("postcode"),
                country=request.form.get("country"),
            )
            flash("Business profile updated.", "success")
            return redirect(url_for("organisation_profile.index"))
        except (ValueError, PermissionError) as exc:
            flash(str(exc), "danger")

    profile = OrganisationProfileService.get(context.organisation_id)
    return render_template(
        "organisation_profile/index.html",
        profile=profile,
        can_manage=context.can("settings.manage"),
    )
