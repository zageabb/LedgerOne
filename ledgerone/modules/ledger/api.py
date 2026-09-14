from datetime import date
from decimal import Decimal

from flask import Blueprint, g, jsonify, request

from ledgerone.models.ledger import Journal
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError, LedgerService

api_bp = Blueprint("ledger_api", __name__, url_prefix="/api/v1/ledger")


def _serialise_money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


@api_bp.get("/accounts")
@require_api("ledger.read")
def accounts():
    rows = LedgerService.list_accounts(g.access_context)
    return jsonify(
        {
            "accounts": [
                {
                    "id": row.id,
                    "code": row.code,
                    "name": row.name,
                    "account_type": row.account_type,
                    "currency": row.currency,
                    "is_active": row.is_active,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/accounts")
@require_api("ledger.accounts.write")
def create_account():
    payload = request.get_json(silent=True) or {}
    try:
        row = LedgerService.create_account(
            g.access_context,
            code=payload.get("code", ""),
            name=payload.get("name", ""),
            account_type=payload.get("account_type", "expense"),
            currency=payload.get("currency"),
            parent_id=payload.get("parent_id"),
        )
        return jsonify({"id": row.id, "code": row.code, "name": row.name}), 201
    except (LedgerError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/journals")
@require_api("ledger.read")
def journals():
    context = g.access_context
    rows = (
        Journal.query.filter_by(organisation_id=context.organisation_id)
        .order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        .limit(min(int(request.args.get("limit", 100)), 500))
        .all()
    )
    return jsonify(
        {
            "journals": [
                {
                    "id": row.id,
                    "date": row.journal_date.isoformat(),
                    "reference": row.reference,
                    "description": row.description,
                    "status": row.status,
                    "source_module": row.source_module,
                    "debit": _serialise_money(row.total_debit),
                    "credit": _serialise_money(row.total_credit),
                    "lines": [
                        {
                            "id": line.id,
                            "account_id": line.account_id,
                            "description": line.description,
                            "debit": _serialise_money(line.debit),
                            "credit": _serialise_money(line.credit),
                            "dimensions": line.dimensions,
                        }
                        for line in row.lines
                    ],
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/journals")
@require_api("ledger.journals.post")
def post_journal():
    payload = request.get_json(silent=True) or {}
    try:
        journal_date = date.fromisoformat(payload.get("date") or date.today().isoformat())
        journal = LedgerService.post_journal(
            g.access_context,
            journal_date=journal_date,
            description=payload.get("description", "API journal"),
            reference=payload.get("reference"),
            lines=payload.get("lines") or [],
            source_module=payload.get("source_module", "api"),
            source_reference=payload.get("source_reference"),
            metadata=payload.get("metadata") or {},
        )
        return jsonify({"id": journal.id, "status": journal.status}), 201
    except (LedgerError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/trial-balance")
@require_api("ledger.read")
def trial_balance():
    rows = LedgerService.trial_balance(g.access_context)
    return jsonify(
        {
            "rows": [
                {
                    **row,
                    "debit": _serialise_money(row["debit"]),
                    "credit": _serialise_money(row["credit"]),
                    "balance": _serialise_money(row["balance"]),
                }
                for row in rows
            ]
        }
    )
