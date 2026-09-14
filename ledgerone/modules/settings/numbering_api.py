from flask import Blueprint, g, jsonify, request

from ledgerone.security import require_api
from ledgerone.services.numbering import NumberSequenceService

api_bp = Blueprint("numbering_api", __name__, url_prefix="/api/v1/settings/numbering")


@api_bp.get("")
@require_api("settings.read")
def get_numbering():
    rows = NumberSequenceService.list_sequences(g.access_context.organisation_id)
    return jsonify({"sequences": [NumberSequenceService.serialise(row) for row in rows]})


@api_bp.patch("/<sequence_key>")
@require_api("settings.manage")
def update_numbering(sequence_key):
    payload = request.get_json(silent=True) or {}
    try:
        current = NumberSequenceService.get(g.access_context.organisation_id, sequence_key)
        row = NumberSequenceService.update(
            g.access_context,
            sequence_key,
            prefix=payload.get("prefix", current.prefix),
            suffix=payload.get("suffix", current.suffix),
            next_value=payload.get("next_value", current.next_value),
            padding=payload.get("padding", current.padding),
        )
        return jsonify(NumberSequenceService.serialise(row))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
