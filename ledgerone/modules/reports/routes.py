from datetime import date

from flask import Blueprint, render_template, request
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


@bp.get("/aging")
@login_required
@require_module("reports")
def aging():
    raw = (request.args.get("as_of") or "").strip()
    try:
        as_of = date.fromisoformat(raw) if raw else date.today()
    except ValueError:
        as_of = date.today()
    context = browser_context()
    return render_template(
        "reports/aging.html",
        as_of=as_of,
        receivables=ReportsService.aged_receivables(context, as_of=as_of),
        payables=ReportsService.aged_payables(context, as_of=as_of),
    )
