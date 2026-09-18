from datetime import date
from decimal import Decimal

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.tax.services import TaxError, TaxService
from ledgerone.security import require_api

api_bp = Blueprint("tax_api", __name__, url_prefix="/api/v1/tax")


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


def _period(context, row):
    return {
        "id": row.id,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
        "summary": _json_value(TaxService.return_period_summary(context, row.id)),
        "source_population": (row.snapshot_json or {}).get("population") if row.status in {"final", "submitted"} else None,
        "finalised_at": row.finalised_at.isoformat() if row.finalised_at else None,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "submission_reference": row.submission_reference,
        "submission_note": row.submission_note,
    }


def _adjustment(row):
    return {
        "id": row.id,
        "tax_point": row.tax_point.isoformat(),
        "box_number": row.box_number,
        "amount": str(row.amount),
        "reason": row.reason,
        "evidence_reference": row.evidence_reference,
        "return_period_id": row.return_period_id,
        "created_at": row.created_at.isoformat(),
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
    active_only = request.args.get("active_only", "true").lower() not in {"0", "false", "no"}
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
        return jsonify(_json_value(TaxService.vat_return(g.access_context, start_date=start_date, end_date=end_date)))
    except (KeyError, TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/return-periods")
@require_api("tax.read")
def return_periods():
    try:
        return jsonify({"return_periods": [_period(g.access_context, row) for row in TaxService.list_return_periods(g.access_context)]})
    except (TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/return-periods")
@require_api("tax.manage")
def create_return_period():
    payload = request.get_json(silent=True) or {}
    try:
        row = TaxService.create_return_period(
            g.access_context,
            start_date=date.fromisoformat(payload["start_date"]),
            end_date=date.fromisoformat(payload["end_date"]),
        )
        return jsonify(_period(g.access_context, row)), 201
    except (KeyError, TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/return-periods/<period_id>")
@require_api("tax.read")
def return_period(period_id):
    try:
        return jsonify(_period(g.access_context, TaxService.get_return_period(g.access_context, period_id)))
    except (TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 404


@api_bp.post("/return-periods/<period_id>/finalise")
@require_api("tax.manage")
def finalise_return(period_id):
    try:
        row = TaxService.finalise_return_period(g.access_context, period_id)
        return jsonify(_period(g.access_context, row))
    except (TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/return-periods/<period_id>/submit")
@require_api("tax.manage")
def submit_return(period_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = TaxService.mark_return_submitted(
            g.access_context,
            period_id,
            submission_reference=payload.get("submission_reference", ""),
            submission_note=payload.get("submission_note"),
        )
        return jsonify(_period(g.access_context, row))
    except (TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/adjustments")
@require_api("tax.read")
def adjustments():
    try:
        start_date = date.fromisoformat(request.args["from_date"]) if request.args.get("from_date") else None
        end_date = date.fromisoformat(request.args["to_date"]) if request.args.get("to_date") else None
        return jsonify({"adjustments": [_adjustment(row) for row in TaxService.list_adjustments(g.access_context, start_date=start_date, end_date=end_date)]})
    except (TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/adjustments")
@require_api("tax.manage")
def create_adjustment():
    payload = request.get_json(silent=True) or {}
    try:
        row = TaxService.create_adjustment(
            g.access_context,
            tax_point=date.fromisoformat(payload["tax_point"]),
            box_number=payload.get("box_number", ""),
            amount=payload.get("amount", 0),
            reason=payload.get("reason", ""),
            evidence_reference=payload.get("evidence_reference"),
        )
        return jsonify(_adjustment(row)), 201
    except (KeyError, TaxError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
