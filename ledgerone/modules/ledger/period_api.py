from flask import Blueprint, g, jsonify, request

from ledgerone.security import require_api
from ledgerone.services.period_policy import PeriodPolicyError, PeriodPolicyService


period_api_bp = Blueprint(
    "ledger_period_policy_api", __name__, url_prefix="/api/v1/ledger"
)


@period_api_bp.get("/period-policy")
@require_api("ledger.read")
def get_period_policy():
    return jsonify({"mode": PeriodPolicyService.get_policy(g.access_context)})


@period_api_bp.put("/period-policy")
@require_api("ledger.periods.manage")
def update_period_policy():
    payload = request.get_json(silent=True) or {}
    try:
        mode = PeriodPolicyService.set_policy(
            g.access_context,
            mode=payload.get("mode", "required"),
        )
        return jsonify({"mode": mode})
    except (PeriodPolicyError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@period_api_bp.post("/periods/<period_id>/status")
@require_api("ledger.periods.manage")
def set_period_status(period_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = PeriodPolicyService.set_period_status(
            g.access_context,
            period_id,
            status=payload.get("status", "open"),
            reason=payload.get("reason"),
        )
        return jsonify(
            {
                "id": row.id,
                "status": row.status,
                "locked_at": row.locked_at.isoformat() if row.locked_at else None,
            }
        )
    except (PeriodPolicyError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
