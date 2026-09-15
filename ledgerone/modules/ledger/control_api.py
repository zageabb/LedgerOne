from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.security import require_api
from ledgerone.services.control_accounts import ControlAccountService

control_api_bp = Blueprint(
    "ledger_control_api", __name__, url_prefix="/api/v1/ledger"
)


def _money(value):
    return str(value)


@control_api_bp.get("/control-accounts")
@require_api("ledger.read")
def control_accounts():
    rows = ControlAccountService.list_accounts(g.access_context)
    return jsonify(
        {
            "accounts": [
                {
                    "id": row.id,
                    "code": row.code,
                    "name": row.name,
                    "account_type": row.account_type,
                    "control_role": (row.metadata_json or {}).get("control_role") or "generic",
                    "control_owner_module": (row.metadata_json or {}).get("control_owner_module"),
                    "allowed_modules": (row.metadata_json or {}).get("control_allowed_modules") or [],
                }
                for row in rows
            ]
        }
    )


@control_api_bp.post("/control-adjustments")
@require_api("ledger.control_accounts.adjust")
def control_adjustment():
    payload = request.get_json(silent=True) or {}
    try:
        journal = ControlAccountService.post_adjustment(
            g.access_context,
            journal_date=date.fromisoformat(payload.get("date") or date.today().isoformat()),
            description=payload.get("description") or "Control-account adjustment",
            reference=payload.get("reference"),
            reason=payload.get("reason") or "",
            lines=payload.get("lines") or [],
        )
        return jsonify(
            {
                "id": journal.id,
                "status": journal.status,
                "source_module": journal.source_module,
                "reason": (journal.metadata_json or {}).get("control_adjustment_reason"),
                "debit": _money(journal.total_debit),
                "credit": _money(journal.total_credit),
            }
        ), 201
    except (KeyError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
