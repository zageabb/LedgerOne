from datetime import date

from flask import Blueprint, render_template, request
from flask_login import login_required

from ledgerone.models.ledger import Account
from ledgerone.modules.reports.services import ReportsService
from ledgerone.security import browser_context, require_module

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _safe_year_back(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def _period_args() -> tuple[date, date]:
    raw_to = (request.args.get("to_date") or "").strip()
    to_date = date.fromisoformat(raw_to) if raw_to else date.today()
    raw_from = (request.args.get("from_date") or "").strip()
    from_date = date.fromisoformat(raw_from) if raw_from else date(to_date.year, 1, 1)
    if to_date < from_date:
        raise ValueError("Report end date cannot be before start date")
    return from_date, to_date


@bp.get("/")
@login_required
@require_module("reports")
def index():
    context = browser_context()
    try:
        from_date, to_date = _period_args()
        compare_enabled = request.args.get("compare", "1") != "0"
    except ValueError:
        to_date = date.today()
        from_date = date(to_date.year, 1, 1)
        compare_enabled = True

    compare_from = _safe_year_back(from_date) if compare_enabled else None
    compare_to = _safe_year_back(to_date) if compare_enabled else None
    report = ReportsService.summary(
        context,
        from_date=from_date,
        to_date=to_date,
        compare_from=compare_from,
        compare_to=compare_to,
        compare_as_of=compare_to,
    )
    return render_template(
        "reports/index.html",
        report=report,
        from_date=from_date,
        to_date=to_date,
        compare_enabled=compare_enabled,
        compare_from=compare_from,
        compare_to=compare_to,
    )


@bp.get("/general-ledger")
@login_required
@require_module("reports")
def general_ledger():
    context = browser_context()
    try:
        from_date, to_date = _period_args()
    except ValueError:
        to_date = date.today()
        from_date = date(to_date.year, 1, 1)
    account_id = (request.args.get("account_id") or "").strip() or None
    report = ReportsService.general_ledger(
        context,
        from_date=from_date,
        to_date=to_date,
        account_id=account_id,
    )
    accounts = (
        Account.query.filter_by(organisation_id=context.organisation_id)
        .order_by(Account.code.asc())
        .all()
    )
    return render_template(
        "reports/general_ledger.html",
        report=report,
        accounts=accounts,
        selected_account_id=account_id,
        from_date=from_date,
        to_date=to_date,
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
