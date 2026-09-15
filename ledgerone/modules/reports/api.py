from datetime import date
from decimal import Decimal

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.reports.services import ReportsService
from ledgerone.security import require_api

api_bp = Blueprint("reports_api", __name__, url_prefix="/api/v1/reports")


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _date_arg(name: str, default: date | None = None) -> date | None:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return default
    return date.fromisoformat(raw)


def _as_of():
    return _date_arg("as_of", date.today())


def _period_dates() -> tuple[date, date]:
    to_date = _date_arg("to_date", date.today())
    from_date = _date_arg("from_date", date(to_date.year, 1, 1))
    return from_date, to_date


def _serialise_aging(report):
    return {
        "as_of": report["as_of"].isoformat(),
        "rows": [
            {
                **row,
                "document_date": row["document_date"].isoformat(),
                "due_date": row["due_date"].isoformat(),
                "outstanding": str(row["outstanding"]),
            }
            for row in report["rows"]
        ],
        "totals_by_currency": {
            currency: {key: str(value) for key, value in totals.items()}
            for currency, totals in report["totals_by_currency"].items()
        },
    }


@api_bp.get("/summary")
@require_api("reports.read")
def summary():
    try:
        from_date, to_date = _period_dates()
        report = ReportsService.summary(
            g.access_context,
            from_date=from_date,
            to_date=to_date,
            compare_from=_date_arg("compare_from"),
            compare_to=_date_arg("compare_to"),
            compare_as_of=_date_arg("compare_as_of"),
        )
        return jsonify(_json_value(report))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/profit-loss")
@require_api("reports.read")
def profit_loss():
    try:
        from_date, to_date = _period_dates()
        return jsonify(
            _json_value(
                ReportsService.profit_and_loss(
                    g.access_context,
                    from_date=from_date,
                    to_date=to_date,
                    compare_from=_date_arg("compare_from"),
                    compare_to=_date_arg("compare_to"),
                )
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/balance-sheet")
@require_api("reports.read")
def balance_sheet():
    try:
        return jsonify(
            _json_value(
                ReportsService.balance_sheet(
                    g.access_context,
                    as_of=_as_of(),
                    compare_as_of=_date_arg("compare_as_of"),
                )
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/trial-balance")
@require_api("reports.read")
def trial_balance():
    try:
        return jsonify(
            _json_value(
                ReportsService.trial_balance(
                    g.access_context,
                    as_of=_as_of(),
                    from_date=_date_arg("from_date"),
                )
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/general-ledger")
@require_api("reports.read")
def general_ledger():
    try:
        from_date, to_date = _period_dates()
        return jsonify(
            _json_value(
                ReportsService.general_ledger(
                    g.access_context,
                    from_date=from_date,
                    to_date=to_date,
                    account_id=(request.args.get("account_id") or "").strip() or None,
                )
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/aged-receivables")
@require_api("reports.read")
def aged_receivables():
    try:
        return jsonify(
            _serialise_aging(
                ReportsService.aged_receivables(g.access_context, as_of=_as_of())
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/aged-payables")
@require_api("reports.read")
def aged_payables():
    try:
        return jsonify(
            _serialise_aging(
                ReportsService.aged_payables(g.access_context, as_of=_as_of())
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/aging")
@require_api("reports.read")
def aging():
    try:
        as_of = _as_of()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(
        {
            "receivables": _serialise_aging(
                ReportsService.aged_receivables(g.access_context, as_of=as_of)
            ),
            "payables": _serialise_aging(
                ReportsService.aged_payables(g.access_context, as_of=as_of)
            ),
        }
    )
