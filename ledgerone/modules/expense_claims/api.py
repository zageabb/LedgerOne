from datetime import date

from flask import Blueprint, g, jsonify, request

from ledgerone.modules.expense_claims.services import ExpenseClaimError, ExpenseClaimService
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError

api_bp = Blueprint("expense_claims_api", __name__, url_prefix="/api/v1/expense-claims")


def _serialise(row):
    return {
        "id": row.id,
        "claim_number": row.claim_number,
        "claimant_user_id": row.claimant_user_id,
        "claimant_name": row.claimant_name,
        "claim_date": row.claim_date.isoformat(),
        "currency": row.currency,
        "status": row.status,
        "subtotal": str(row.subtotal),
        "tax_total": str(row.tax_total),
        "total": str(row.total),
        "reimbursement_account_id": row.reimbursement_account_id,
        "posted_journal_id": row.posted_journal_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "lines": [
            {
                "id": line.id,
                "line_number": line.line_number,
                "expense_date": line.expense_date.isoformat(),
                "merchant": line.merchant,
                "description": line.description,
                "net_amount": str(line.net_amount),
                "tax_amount": str(line.tax_amount),
                "tax_code_id": line.tax_code_id,
                "expense_account_id": line.expense_account_id,
            }
            for line in row.lines
        ],
    }


@api_bp.get("")
@require_api("expense_claims.read")
def list_claims():
    rows = ExpenseClaimService.list_claims(
        g.access_context, min(max(int(request.args.get("limit", 100)), 1), 500)
    )
    return jsonify({"expense_claims": [_serialise(row) for row in rows]})


@api_bp.post("")
@require_api("expense_claims.write")
def create_claim():
    payload = request.get_json(silent=True) or {}
    try:
        row = ExpenseClaimService.create_claim(
            g.access_context,
            claimant_name=payload["claimant_name"],
            claim_number=payload["claim_number"],
            claim_date=date.fromisoformat(payload.get("claim_date") or date.today().isoformat()),
            expense_date=date.fromisoformat(payload.get("expense_date") or payload.get("claim_date") or date.today().isoformat()),
            merchant=payload.get("merchant"),
            description=payload.get("description", "Expense"),
            amount=payload["amount"],
            expense_account_id=payload["expense_account_id"],
            reimbursement_account_id=payload.get("reimbursement_account_id"),
            currency=payload.get("currency", "GBP"),
            tax_code_id=payload.get("tax_code_id"),
        )
        return jsonify(_serialise(row)), 201
    except (KeyError, ExpenseClaimError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<claim_id>/lines")
@require_api("expense_claims.write")
def add_line(claim_id):
    payload = request.get_json(silent=True) or {}
    try:
        _, row = ExpenseClaimService.add_line(
            g.access_context,
            claim_id,
            expense_date=date.fromisoformat(payload.get("expense_date") or date.today().isoformat()),
            merchant=payload.get("merchant"),
            description=payload.get("description", "Expense"),
            amount=payload["amount"],
            expense_account_id=payload["expense_account_id"],
            tax_code_id=payload.get("tax_code_id"),
        )
        return jsonify(_serialise(row)), 201
    except (KeyError, ExpenseClaimError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<claim_id>/submit")
@require_api("expense_claims.write")
def submit_claim(claim_id):
    try:
        return jsonify(_serialise(ExpenseClaimService.submit(g.access_context, claim_id)))
    except (ExpenseClaimError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<claim_id>/approve")
@require_api("expense_claims.approve")
def approve_claim(claim_id):
    payload = request.get_json(silent=True) or {}
    try:
        row, journal = ExpenseClaimService.approve_and_post(
            g.access_context,
            claim_id,
            posting_date=date.fromisoformat(payload.get("posting_date") or date.today().isoformat()),
        )
        return jsonify({"expense_claim": _serialise(row), "journal_id": journal.id})
    except (ExpenseClaimError, LedgerError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/<claim_id>/reject")
@require_api("expense_claims.approve")
def reject_claim(claim_id):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            _serialise(
                ExpenseClaimService.reject(
                    g.access_context, claim_id, reason=payload.get("reason")
                )
            )
        )
    except (ExpenseClaimError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400
