from flask import Blueprint, render_template
from flask_login import login_required

from ledgerone.modules.reports.services import ReportsService
from ledgerone.security import browser_context, require_module

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.get("/")
@login_required
@require_module("reports")
def index():
    return render_template(
        "reports/index.html",
        report=ReportsService.summary(browser_context()),
    )
