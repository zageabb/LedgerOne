from datetime import date
from decimal import Decimal

from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_

from ledgerone.models.ledger import Account, Journal
from ledgerone.module_registry import module_registry
from ledgerone.security import require_api
from ledgerone.services.ledger import LedgerError, LedgerService

api_bp = Blueprint("ledger_api", __name__, url_prefix="/api/v1/ledger")


def _serialise_money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _page_args(default_per_page=100, max_per_page=500):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(int(request.args.get("per_page", default_per_page)), max_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    return page, per_page


def _pagination(page, per_page, total):
    pages = max(1, (total + per_page - 1) // per_page) if total else 0
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_previous": page > 1,
        "has_next": page < pages,
    }


@api_bp.get("/accounts")
@require_api("ledger.read")
def accounts():
    context = g.access_context
    query = Account.query.filter_by(organisation_id=context.organisation_id)
    account_type = (request.args.get("account_type") or "").strip().lower()
    if account_type:
        query = query.filter(Account.account_type == account_type)
    active = (request.args.get("active") or "").strip().lower()
    if active in {"1", "true", "yes"}:
        query = query.filter(Account.is_active.is_(True))
    elif active in {"0", "false", "no"}:
        query = query.filter(Account.is_active.is_(False))
    text = (request.args.get("q") or "").strip()
    if text:
        pattern = f"%{text}%"
        query = query.filter(or_(Account.code.ilike(pattern), Account.name.ilike(pattern)))
    total = query.count()
    page, per_page = _page_args()
    rows = (
        query.order_by(Account.code.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
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
            ],
            "pagination": _pagination(page, per_page, total),
            "filters": {"q": text or None, "account_type": account_type or None, "active": active or None},
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


@api_bp.get("/periods")
@require_api("ledger.read")
def periods():
    rows = LedgerService.list_periods(g.access_context)
    return jsonify(
        {
            "periods": [
                {
                    "id": row.id,
                    "name": row.name,
                    "start_date": row.start_date.isoformat(),
                    "end_date": row.end_date.isoformat(),
                    "status": row.status,
                    "locked_at": row.locked_at.isoformat() if row.locked_at else None,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/periods")
@require_api("ledger.periods.manage")
def create_period():
    payload = request.get_json(silent=True) or {}
    try:
        row = LedgerService.create_period(
            g.access_context,
            name=payload.get("name", ""),
            start_date=date.fromisoformat(payload["start_date"]),
            end_date=date.fromisoformat(payload["end_date"]),
        )
        return jsonify({"id": row.id, "name": row.name, "status": row.status}), 201
    except (KeyError, LedgerError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/periods/<period_id>/lock")
@require_api("ledger.periods.manage")
def set_period_lock(period_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = LedgerService.set_period_locked(
            g.access_context,
            period_id,
            locked=bool(payload.get("locked", True)),
        )
        return jsonify({"id": row.id, "status": row.status})
    except (LedgerError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/journals")
@require_api("ledger.read")
def journals():
    context = g.access_context
    query = Journal.query.filter_by(organisation_id=context.organisation_id)
    source_module = (request.args.get("source_module") or "").strip()
    status = (request.args.get("status") or "").strip()
    reference = (request.args.get("reference") or "").strip()
    text = (request.args.get("q") or "").strip()
    if source_module:
        query = query.filter(Journal.source_module == source_module)
    if status:
        query = query.filter(Journal.status == status)
    if reference:
        query = query.filter(Journal.reference.ilike(f"%{reference}%"))
    if request.args.get("from_date"):
        try:
            query = query.filter(Journal.journal_date >= date.fromisoformat(request.args["from_date"]))
        except ValueError:
            return jsonify({"error": "from_date must be YYYY-MM-DD"}), 400
    if request.args.get("to_date"):
        try:
            query = query.filter(Journal.journal_date <= date.fromisoformat(request.args["to_date"]))
        except ValueError:
            return jsonify({"error": "to_date must be YYYY-MM-DD"}), 400
    if text:
        pattern = f"%{text}%"
        query = query.filter(
            or_(
                Journal.reference.ilike(pattern),
                Journal.description.ilike(pattern),
                Journal.source_reference.ilike(pattern),
            )
        )
    total = query.count()
    page, per_page = _page_args()
    rows = (
        query.order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
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
                    "source_reference": row.source_reference,
                    "reversal_of_id": row.reversal_of_id,
                    "immutable": True,
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
            ],
            "pagination": _pagination(page, per_page, total),
            "filters": {
                "q": text or None,
                "source_module": source_module or None,
                "status": status or None,
                "reference": reference or None,
                "from_date": request.args.get("from_date"),
                "to_date": request.args.get("to_date"),
            },
        }
    )


@api_bp.post("/journals")
@require_api("ledger.journals.post")
def post_journal():
    payload = request.get_json(silent=True) or {}
    try:
        journal_date = date.fromisoformat(payload.get("date") or date.today().isoformat())
        if module_registry.is_enabled(g.access_context.organisation_id, "workflows"):
            from ledgerone.modules.workflows.journal_requests import JournalWorkflowService

            workflow = JournalWorkflowService.create_request(
                g.access_context,
                journal_date=journal_date,
                description=payload.get("description", "API journal"),
                reference=payload.get("reference"),
                lines=payload.get("lines") or [],
                source_module="api",
                source_reference=payload.get("source_reference"),
                metadata={**(payload.get("metadata") or {}), "created_by": "ledger_api"},
            )
            return jsonify({
                "workflow_instance_id": workflow.id,
                "status": workflow.status,
                "posted": False,
                "immutable": False,
            }), 201

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
        return jsonify({"id": journal.id, "status": journal.status, "immutable": True, "posted": True}), 201
    except (LedgerError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/journals/<journal_id>/reverse")
@require_api("ledger.journals.reverse")
def reverse_journal(journal_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = LedgerService.reverse_journal(
            g.access_context,
            journal_id,
            reversal_date=date.fromisoformat(payload.get("date") or date.today().isoformat()),
            reason=payload.get("reason"),
        )
        return jsonify(
            {
                "id": row.id,
                "reference": row.reference,
                "reversal_of_id": row.reversal_of_id,
                "status": row.status,
                "immutable": True,
            }
        ), 201
    except (LedgerError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/opening-balances")
@require_api("ledger.read")
def opening_balance_batches():
    rows = LedgerService.list_opening_balance_batches(g.access_context)
    return jsonify(
        {
            "batches": [
                {
                    "id": row.id,
                    "as_of_date": row.as_of_date.isoformat(),
                    "reference": row.reference,
                    "description": row.description,
                    "balancing_account_id": row.balancing_account_id,
                    "journal_id": row.journal_id,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/opening-balances")
@require_api("ledger.opening_balances.manage")
def create_opening_balance_batch():
    payload = request.get_json(silent=True) or {}
    try:
        row = LedgerService.create_opening_balance_batch(
            g.access_context,
            as_of_date=date.fromisoformat(payload.get("as_of_date") or date.today().isoformat()),
            entries=payload.get("entries") or [],
            balancing_account_id=payload.get("balancing_account_id"),
            reference=payload.get("reference"),
            description=payload.get("description") or "Opening balances",
        )
        return jsonify(
            {
                "id": row.id,
                "journal_id": row.journal_id,
                "reference": row.reference,
                "as_of_date": row.as_of_date.isoformat(),
            }
        ), 201
    except (LedgerError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/recurring")
@require_api("ledger.read")
def recurring_journals():
    rows = LedgerService.list_recurring_journals(g.access_context)
    return jsonify(
        {
            "recurring": [
                {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "reference": row.reference,
                    "frequency": row.frequency,
                    "next_run_date": row.next_run_date.isoformat(),
                    "end_date": row.end_date.isoformat() if row.end_date else None,
                    "is_active": row.is_active,
                    "last_run_date": row.last_run_date.isoformat() if row.last_run_date else None,
                    "run_count": row.run_count,
                    "lines": row.template_lines,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/recurring")
@require_api("ledger.recurring.manage")
def create_recurring_journal():
    payload = request.get_json(silent=True) or {}
    try:
        row = LedgerService.create_recurring_journal(
            g.access_context,
            name=payload.get("name", ""),
            description=payload.get("description", ""),
            reference=payload.get("reference"),
            frequency=payload.get("frequency", "monthly"),
            next_run_date=date.fromisoformat(payload.get("next_run_date") or date.today().isoformat()),
            end_date=date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None,
            lines=payload.get("lines") or [],
        )
        return jsonify(
            {
                "id": row.id,
                "name": row.name,
                "frequency": row.frequency,
                "next_run_date": row.next_run_date.isoformat(),
                "is_active": row.is_active,
            }
        ), 201
    except (LedgerError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/recurring/<recurring_id>/run")
@require_api("ledger.recurring.manage")
def run_recurring_journal(recurring_id):
    try:
        journal, run, schedule = LedgerService.run_recurring_journal(g.access_context, recurring_id)
        return jsonify(
            {
                "journal_id": journal.id,
                "run_id": run.id,
                "scheduled_date": run.scheduled_date.isoformat(),
                "next_run_date": schedule.next_run_date.isoformat(),
                "is_active": schedule.is_active,
            }
        ), 201
    except (LedgerError, PermissionError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/recurring/<recurring_id>/active")
@require_api("ledger.recurring.manage")
def set_recurring_active(recurring_id):
    payload = request.get_json(silent=True) or {}
    try:
        row = LedgerService.set_recurring_journal_active(
            g.access_context,
            recurring_id,
            active=bool(payload.get("active", True)),
        )
        return jsonify({"id": row.id, "is_active": row.is_active})
    except (LedgerError, PermissionError) as exc:
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
