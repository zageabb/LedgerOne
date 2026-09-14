from flask import Blueprint, g, jsonify

from ledgerone.modules.reports.services import ReportsService
from ledgerone.security import require_api

api_bp = Blueprint("reports_api", __name__, url_prefix="/api/v1/reports")


def _serialise(report):
    result = {}
    for key, value in report.items():
        if isinstance(value, list):
            result[key] = [
                {item_key: str(item_value) if item_key in {"debit", "credit", "balance"} else item_value
                 for item_key, item_value in row.items()}
                for row in value
            ]
        else:
            result[key] = str(value)
    return result


@api_bp.get("/summary")
@require_api("reports.read")
def summary():
    return jsonify(_serialise(ReportsService.summary(g.access_context)))


@api_bp.get("/profit-loss")
@require_api("reports.read")
def profit_loss():
    report = ReportsService.summary(g.access_context)
    return jsonify(
        {
            "income": _serialise({"rows": report["income"]})["rows"],
            "expenses": _serialise({"rows": report["expenses"]})["rows"],
            "total_income": str(report["total_income"]),
            "total_expenses": str(report["total_expenses"]),
            "net_profit": str(report["net_profit"]),
        }
    )


@api_bp.get("/balance-sheet")
@require_api("reports.read")
def balance_sheet():
    report = ReportsService.summary(g.access_context)
    return jsonify(
        {
            "assets": _serialise({"rows": report["assets"]})["rows"],
            "liabilities": _serialise({"rows": report["liabilities"]})["rows"],
            "equity": _serialise({"rows": report["equity"]})["rows"],
            "total_assets": str(report["total_assets"]),
            "total_liabilities": str(report["total_liabilities"]),
            "total_equity": str(report["total_equity"]),
            "net_worth": str(report["net_worth"]),
        }
    )
