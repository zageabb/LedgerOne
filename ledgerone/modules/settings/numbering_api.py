from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.security import require_api
from ledgerone.services.numbering import NumberingError, NumberSequenceService

numbering_api_bp = Blueprint(
    "settings_numbering_api",
    __name__,
    url_prefix="/api/v1/settings/numbering",
)


def _allocation_payload(row):
    return {
        "id": row.id,
        "sequence_key": row.sequence_key,
        "reset_key": row.reset_key,
        "sequence_value": row.sequence_value,
        "formatted_number": row.formatted_number,
        "status": row.status,
        "issue_date": row.issue_date.isoformat(),
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "manual_override": row.manual_override,
        "reason": row.reason,
        "allocated_by_user_id": row.allocated_by_user_id,
        "allocated_at": row.allocated_at.isoformat() if row.allocated_at else None,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "voided_at": row.voided_at.isoformat() if row.voided_at else None,
    }


@numbering_api_bp.get("")
@require_api("settings.manage")
def list_number_sequences():
    rows = NumberSequenceService.list_sequences(g.access_context)
    return jsonify(
        {
            "sequences": [NumberSequenceService.serialise(row) for row in rows],
        }
    )


@numbering_api_bp.get("/<sequence_key>")
@require_api("settings.manage")
def get_number_sequence(sequence_key: str):
    try:
        sequence = NumberSequenceService.get(g.access_context.organisation_id, sequence_key)
        allocations = NumberSequenceService.list_allocations(
            g.access_context,
            sequence_key=sequence_key,
            limit=min(int(request.args.get("limit", 250)), 1000),
        )
        return jsonify(
            {
                "sequence": NumberSequenceService.serialise(sequence),
                "gap_report": NumberSequenceService.gap_report(g.access_context, sequence_key),
                "allocations": [_allocation_payload(row) for row in allocations],
            }
        )
    except (NumberingError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@numbering_api_bp.put("/<sequence_key>")
@require_api("settings.manage")
def update_number_sequence(sequence_key: str):
    payload = request.get_json(silent=True) or {}
    try:
        sequence = NumberSequenceService.update(
            g.access_context,
            sequence_key,
            prefix=payload.get("prefix", ""),
            suffix=payload.get("suffix", ""),
            starting_value=payload.get("starting_value", 1),
            padding=payload.get("padding", 4),
            reset_policy=payload.get("reset_policy", "never"),
        )
        return jsonify({"sequence": NumberSequenceService.serialise(sequence)})
    except (NumberingError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@numbering_api_bp.post("/<sequence_key>/void-next")
@require_api("settings.manage")
def void_next_number(sequence_key: str):
    payload = request.get_json(silent=True) or {}
    try:
        issue_date = date.fromisoformat(payload.get("issue_date") or date.today().isoformat())
        allocation = NumberSequenceService.void_next(
            g.access_context,
            sequence_key,
            issue_date=issue_date,
            reason=payload.get("reason", ""),
        )
        return jsonify({"allocation": _allocation_payload(allocation)}), 201
    except (NumberingError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
