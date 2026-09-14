from flask import Blueprint, jsonify

from ledgerone.module_registry import module_registry
from ledgerone.security import require_api

api_bp = Blueprint("core_api", __name__, url_prefix="/api/v1/system")


@api_bp.get("/health")
def health():
    return jsonify({"status": "ok", "application": "LedgerOne"})


@api_bp.get("/modules")
@require_api("core.read")
def modules():
    return jsonify(
        {
            "modules": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "default_enabled": item.default_enabled,
                    "always_on": item.always_on,
                    "dependencies": list(item.dependencies),
                    "permissions": list(item.permissions),
                }
                for item in module_registry.manifests
            ]
        }
    )
