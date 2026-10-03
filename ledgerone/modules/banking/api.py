from datetime import date

import csv
import io

from flask import Blueprint, Response, g, jsonify, request

from ledgerone.security import require_api
from ledgerone.modules.banking.services import BankingService
from ledgerone.services.ledger import LedgerError

api_bp = Blueprint("banking_api", __name__, url_prefix="/api/v1/banking")


@api_bp.get("/accounts")
@require_api("banking.read")
def accounts():
    rows = BankingService.list_accounts(g.access_context)
    return jsonify(
        {
            "accounts": [
                {
                    "id": row.id,
                    "name": row.name,
                    "institution": row.institution,
                    "currency": row.currency,
                    "ledger_account_id": row.ledger_account_id,
                    "is_active": row.is_active,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/accounts")
@require_api("banking.write")
def create_account():
    payload = request.get_json(silent=True) or {}
    try:
        row = BankingService.create_account(
            g.access_context,
            name=payload.get("name", "Bank account"),
            institution=payload.get("institution"),
            currency=payload.get("currency", "GBP"),
            ledger_account_id=payload.get("ledger_account_id"),
        )
        return jsonify({"id": row.id}), 201
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/transactions")
@require_api("banking.read")
def transactions():
    rows = BankingService.list_transactions(
        g.access_context,
        min(int(request.args.get("limit", 100)), 500),
        status=request.args.get("status") or None,
    )
    return jsonify(
        {
            "transactions": [
                {
                    "id": row.id,
                    "bank_account_id": row.bank_account_id,
                    "date": row.transaction_date.isoformat(),
                    "description": row.description,
                    "amount": str(row.amount),
                    "status": row.status,
                    "matched_journal_id": row.matched_journal_id,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/transactions")
@require_api("banking.write")
def add_transaction():
    payload = request.get_json(silent=True) or {}
    try:
        row = BankingService.add_transaction(
            g.access_context,
            bank_account_id=payload["bank_account_id"],
            transaction_date=date.fromisoformat(payload.get("date") or date.today().isoformat()),
            description=payload.get("description", "Imported bank transaction"),
            amount=payload.get("amount", 0),
            external_id=payload.get("external_id"),
            raw_payload=payload.get("raw_payload") or {},
        )
        return jsonify({"id": row.id, "status": row.status}), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/transactions/<transaction_id>/candidates")
@require_api("banking.reconcile")
def reconciliation_candidates(transaction_id):
    try:
        rows = BankingService.reconciliation_candidates(
            g.access_context,
            transaction_id,
            days=min(max(int(request.args.get("days", 7)), 0), 90),
            limit=min(max(int(request.args.get("limit", 25)), 1), 100),
        )
        return jsonify(
            {
                "candidates": [
                    {
                        "id": row.id,
                        "date": row.journal_date.isoformat(),
                        "reference": row.reference,
                        "description": row.description,
                        "source_module": row.source_module,
                        "debit": str(row.total_debit),
                        "credit": str(row.total_credit),
                    }
                    for row in rows
                ]
            }
        )
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/transactions/<transaction_id>/match")
@require_api("banking.reconcile")
def match_transaction(transaction_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = BankingService.match_transaction(
            g.access_context,
            transaction_id,
            payload["journal_id"],
        )
        return jsonify(
            {
                "id": row.id,
                "status": row.status,
                "matched_journal_id": row.matched_journal_id,
            }
        )
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/transactions/<transaction_id>/post-and-match")
@require_api("banking.reconcile")
def post_and_match(transaction_id):
    payload = request.get_json(silent=True) or {}
    try:
        transaction, journal = BankingService.post_and_match(
            g.access_context,
            transaction_id,
            offset_account_id=payload["offset_account_id"],
            description=payload.get("description"),
            reference=payload.get("reference"),
        )
        return jsonify(
            {
                "id": transaction.id,
                "status": transaction.status,
                "matched_journal_id": transaction.matched_journal_id,
                "journal_id": journal.id,
            }
        ), 201
    except (KeyError, ValueError, LedgerError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/transactions/<transaction_id>/unmatch")
@require_api("banking.reconcile")
def unmatch_transaction(transaction_id):
    try:
        row = BankingService.unmatch_transaction(g.access_context, transaction_id)
        return jsonify(
            {
                "id": row.id,
                "status": row.status,
                "matched_journal_id": row.matched_journal_id,
            }
        )
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


def _formal_json(context, row):
    return BankingService.formal_reconciliation_evidence(context, row.id)


@api_bp.get("/reconciliations")
@require_api("banking.read")
def formal_reconciliations():
    rows = BankingService.list_formal_reconciliations(
        g.access_context, request.args.get("bank_account_id") or None
    )
    return jsonify({"reconciliations": [_formal_json(g.access_context, row) for row in rows]})


@api_bp.post("/reconciliations")
@require_api("banking.reconcile")
def create_formal_reconciliation():
    payload = request.get_json(silent=True) or {}
    try:
        row = BankingService.create_formal_reconciliation(
            g.access_context,
            bank_account_id=payload["bank_account_id"],
            statement_start_date=date.fromisoformat(payload["statement_start_date"]),
            statement_end_date=date.fromisoformat(payload["statement_end_date"]),
            statement_opening_balance=payload["statement_opening_balance"],
            statement_closing_balance=payload["statement_closing_balance"],
            explained_difference=payload.get("explained_difference", 0),
            explanation=payload.get("explanation"),
        )
        return jsonify(_formal_json(g.access_context, row)), 201
    except (KeyError, ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.patch("/reconciliations/<reconciliation_id>")
@require_api("banking.reconcile")
def refresh_formal_reconciliation(reconciliation_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = BankingService.refresh_formal_reconciliation(
            g.access_context,
            reconciliation_id,
            explained_difference=payload.get("explained_difference"),
            explanation=payload.get("explanation") if "explanation" in payload else None,
        )
        return jsonify(_formal_json(g.access_context, row))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/reconciliations/<reconciliation_id>/finalise")
@require_api("banking.reconcile")
def finalise_formal_reconciliation(reconciliation_id):
    try:
        row = BankingService.finalise_formal_reconciliation(
            g.access_context, reconciliation_id
        )
        return jsonify(_formal_json(g.access_context, row))
    except (ValueError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/reconciliations/<reconciliation_id>")
@require_api("banking.read")
def formal_reconciliation(reconciliation_id):
    try:
        row = BankingService.get_formal_reconciliation(g.access_context, reconciliation_id)
        return jsonify(_formal_json(g.access_context, row))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@api_bp.get("/reconciliations/<reconciliation_id>/export.csv")
@require_api("banking.read")
def export_formal_reconciliation(reconciliation_id):
    try:
        evidence = BankingService.formal_reconciliation_evidence(
            g.access_context, reconciliation_id
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["LedgerOne formal bank reconciliation", evidence["id"]])
    for key in (
        "status", "statement_start_date", "statement_end_date",
        "statement_opening_balance", "statement_closing_balance",
        "ledger_balance", "unmatched_statement_total",
        "outstanding_book_total", "explained_difference",
        "residual_difference", "explanation", "prepared_by",
        "approved_by", "prepared_at", "approved_at", "finalised_at",
    ):
        writer.writerow([key, evidence.get(key)])
    writer.writerow([])
    writer.writerow(["Statement transactions"])
    writer.writerow(["id", "date", "description", "amount", "status", "journal_id"])
    for item in evidence["snapshot"].get("statement_transactions", []):
        writer.writerow([
            item.get("id"), item.get("date"), item.get("description"),
            item.get("amount"), item.get("status"), item.get("matched_journal_id"),
        ])
    writer.writerow([])
    writer.writerow(["Outstanding book items"])
    writer.writerow(["journal_id", "date", "reference", "description", "amount"])
    for item in evidence["snapshot"].get("outstanding_book_items", []):
        writer.writerow([
            item.get("journal_id"), item.get("date"), item.get("reference"),
            item.get("description"), item.get("amount"),
        ])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="bank-reconciliation-{reconciliation_id}.csv"'
        },
    )
