from datetime import date

from flask import Blueprint, g, jsonify, render_template, request
from flask_login import login_required

from ledgerone.security import browser_context, require_api, require_module
from ledgerone.services.control_accounts import ControlAccountService

bp = Blueprint(
    "control_account_reports", __name__, url_prefix="/reports/control-accounts"
)
api_bp = Blueprint(
    "control_account_reports_api", __name__, url_prefix="/api/v1/reports/control-accounts"
)


def _as_of():
    raw = (request.args.get("as_of") or "").strip()
    return date.fromisoformat(raw) if raw else date.today()


def _serialise(report):
    return {
        "as_of": report["as_of"].isoformat(),
        "all_configured_reconciled": report["all_configured_reconciled"],
        "rows": [
            {
                **row,
                "ledger_balance": str(row["ledger_balance"]),
                "subledger_balance": str(row["subledger_balance"]),
                "difference": str(row["difference"]),
            }
            for row in report["rows"]
        ],
    }


@bp.get("/")
@login_required
@require_module("reports")
def index():
    try:
        as_of = _as_of()
    except ValueError:
        as_of = date.today()
    report = ControlAccountService.reconciliation(browser_context(), as_of=as_of)
    return render_template(
        "reports/control_accounts.html",
        report=report,
        as_of=as_of,
    )


@api_bp.get("/")
@require_api("reports.read")
def api_index():
    try:
        report = ControlAccountService.reconciliation(g.access_context, as_of=_as_of())
        return jsonify(_serialise(report))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
