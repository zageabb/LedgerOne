from flask import Blueprint, g, jsonify

from ledgerone.models.core import Organisation
from ledgerone.security import require_api

api_bp = Blueprint("auth_api", __name__, url_prefix="/api/v1/auth")


@api_bp.get("/me")
@require_api()
def me():
    context = g.access_context
    organisation = Organisation.query.get(context.organisation_id) if context.organisation_id else None
    return jsonify(
        {
            "identity_type": context.identity_type,
            "user_id": context.user_id,
            "api_key_id": context.api_key_id,
            "organisation": (
                {"id": organisation.id, "name": organisation.name, "base_currency": organisation.base_currency}
                if organisation
                else None
            ),
            "full_access": context.full_access,
            "permissions": sorted(context.permissions),
        }
    )
