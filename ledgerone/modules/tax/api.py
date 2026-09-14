from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.tax.services import TaxError, TaxService
from ledgerone.security import require_api

api_bp = Blueprint("tax_api", __name__, url_prefix="/api/v1/tax")


def _profile(row):
    return {
        "id": row.id,
        "jurisdiction": row.jurisdiction,
        "is_vat_registered": row.is_vat_registered,
        "registration_number": row.registration_number,
        "scheme": row.scheme,
        "return_frequency": row.return_frequency,
    }


def _code(row):
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "rate_percent": str(row.rate_percent),
        "treatment": row.treatment,
        "scope": row.scope,
        "sales_tax_account_id": row.sales_tax_account_id,
        "purchase_tax_account_id": row.purchase_tax_account_id,
        "is_active": row.is_active,
    }


@api_bp.get("/profile")
@require_api("tax.read")
def profile():
    return jsonify({"profile": _profile(TaxService.profile(g.access_context))})


@api_bp.patch("/profile")
@require_api("tax.manage")
def update_profile():
    payload = request.get_json(silent=True) or {}
    current = TaxService.profile(g.access_context)
    try:
        row = TaxService.update_profile(
            g.access_context,
            jurisdiction=payload.get("jurisdiction", current.jurisdiction),
            is_vat_registered=payload.get("is_vat_registered", current.is_vat_registered),
            registration_number=payload.get("registration_number", current.registration_number),
            scheme=payload.get("scheme", current.scheme),
            return_frequency=payload.get("return_frequency", current.return_frequency),
        )
        return jsonify({"profile": _profile(row)})
    except (TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/codes")
@require_api("tax.read")
def codes():
    active_only = (request.args.get("active_only", "true").lower() not in {"0", "false", "no"})
    return jsonify({"tax_codes": [_code(row) for row in TaxService.list_codes(g.access_context, active_only=active_only)]})


@api_bp.post("/codes")
@require_api("tax.manage")
def create_code():
    payload = request.get_json(silent=True) or {}
    try:
        row = TaxService.create_code(
            g.access_context,
            code=payload.get("code", ""),
            name=payload.get("name", ""),
            rate_percent=payload.get("rate_percent", 0),
            treatment=payload.get("treatment", "standard"),
            scope=payload.get("scope", "both"),
            sales_tax_account_id=payload.get("sales_tax_account_id"),
            purchase_tax_account_id=payload.get("purchase_tax_account_id"),
        )
        return jsonify(_code(row)), 201
    except (TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/vat-return")
@require_api("tax.read")
def vat_return():
    try:
        start_date = date.fromisoformat(request.args["from_date"])
        end_date = date.fromisoformat(request.args["to_date"])
        summary = TaxService.vat_return(g.access_context, start_date=start_date, end_date=end_date)
        return jsonify(
            {
                key: (str(value) if hasattr(value, "quantize") else value.isoformat() if hasattr(value, "isoformat") else value)
                for key, value in summary.items()
            }
        )
    except (KeyError, TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
