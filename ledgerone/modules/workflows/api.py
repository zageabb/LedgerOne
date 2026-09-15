from datetime import date
from decimal import Decimal

from flask import Blueprint, g, jsonify, request

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.module_registry import module_registry
from ledgerone.modules.workflows.models import UserAction
from ledgerone.modules.workflows.services import (
    RecurringTransactionService,
    WorkflowError,
    WorkflowService,
)
from ledgerone.security import require_api

api_bp = Blueprint("workflows_api", __name__, url_prefix="/api/v1/workflows")


def _money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01"))) if value is not None else None


def _base_currency(context):
    organisation = db.session.get(Organisation, context.organisation_id)
    return organisation.base_currency if organisation else "GBP"


def _template_json(row):
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "transaction_type": row.transaction_type,
        "amount_mode": row.amount_mode,
        "expected_amount": _money(row.expected_amount),
        "tolerance": _money(row.tolerance),
        "currency": row.currency,
        "bank_account_id": row.bank_account_id,
        "counter_account_id": row.counter_account_id,
        "frequency": row.frequency,
        "next_run_date": row.next_run_date.isoformat(),
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "reference": row.reference,
        "workflow_definition_id": row.workflow_definition_id,
        "posting_mode": row.posting_mode,
        "is_active": row.is_active,
    }


def _item_json(row):
    return {
        "id": row.id,
        "template_id": row.template_id,
        "scheduled_date": row.scheduled_date.isoformat(),
        "transaction_type": row.transaction_type,
        "description": row.description,
        "expected_amount": _money(row.expected_amount),
        "actual_amount": _money(row.actual_amount),
        "currency": row.currency,
        "status": row.status,
        "workflow_instance_id": row.workflow_instance_id,
        "journal_id": row.journal_id,
    }


def _instance_json(row):
    return {
        "id": row.id,
        "definition_id": row.workflow_definition_id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "source_module": row.source_module,
        "title": row.title,
        "amount": _money(row.amount),
        "currency": row.currency,
        "status": row.status,
        "current_step_index": row.current_step_index,
        "originator_user_id": row.originator_user_id,
        "metadata": row.metadata_json,
        "created_at": row.created_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _adapter_for_action(action: UserAction | None):
    if not action or not action.workflow_instance:
        return None
    return module_registry.workflow_adapter(action.workflow_instance.entity_type)


@api_bp.get("/templates")
@require_api("workflows.read")
def templates():
    return jsonify({"templates": [_template_json(row) for row in RecurringTransactionService.list_templates(g.access_context)]})


@api_bp.post("/templates")
@require_api("workflows.write")
def create_template():
    payload = request.get_json(silent=True) or {}
    try:
        row = RecurringTransactionService.create_template(
            g.access_context,
            name=payload.get("name", ""),
            description=payload.get("description"),
            transaction_type=payload.get("transaction_type", "expense"),
            amount_mode=payload.get("amount_mode", "expected"),
            expected_amount=payload.get("expected_amount"),
            tolerance=payload.get("tolerance"),
            currency=payload.get("currency") or _base_currency(g.access_context),
            bank_account_id=payload.get("bank_account_id", ""),
            counter_account_id=payload.get("counter_account_id", ""),
            frequency=payload.get("frequency", "monthly"),
            next_run_date=date.fromisoformat(payload.get("next_run_date") or date.today().isoformat()),
            end_date=date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None,
            reference=payload.get("reference"),
            workflow_definition_id=payload.get("workflow_definition_id"),
        )
        return jsonify(_template_json(row)), 201
    except (WorkflowError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/generate-due")
@require_api("workflows.write")
def generate_due():
    payload = request.get_json(silent=True) or {}
    try:
        through_date = date.fromisoformat(payload.get("through_date") or date.today().isoformat())
        rows = RecurringTransactionService.generate_due(g.access_context, through_date=through_date)
        return jsonify({"generated": [_item_json(row) for row in rows], "count": len(rows)})
    except (WorkflowError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/items")
@require_api("workflows.read")
def items():
    return jsonify({"items": [_item_json(row) for row in RecurringTransactionService.list_items(g.access_context)]})


@api_bp.get("/definitions")
@require_api("workflows.read")
def definitions():
    rows = WorkflowService.list_definitions(g.access_context)
    return jsonify(
        {
            "definitions": [
                {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "entity_type": row.entity_type,
                    "priority": row.priority,
                    "rules": row.rules_json,
                    "steps": row.steps_json,
                    "is_active": row.is_active,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/definitions")
@require_api("workflows.manage")
def create_definition():
    payload = request.get_json(silent=True) or {}
    try:
        row = WorkflowService.create_definition(
            g.access_context,
            name=payload.get("name", ""),
            description=payload.get("description"),
            entity_type=payload.get("entity_type", "scheduled_transaction"),
            transaction_type=payload.get("transaction_type"),
            min_amount=payload.get("min_amount"),
            max_amount=payload.get("max_amount"),
            review_required=bool(payload.get("review_required", True)),
            approval_required=bool(payload.get("approval_required", False)),
            approval_role=payload.get("approval_role"),
            separate_approver=bool(payload.get("separate_approver", True)),
            priority=int(payload.get("priority", 100)),
        )
        return jsonify({"id": row.id, "name": row.name, "rules": row.rules_json, "steps": row.steps_json}), 201
    except (WorkflowError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/instances")
@require_api("workflows.read")
def instances():
    return jsonify({"instances": [_instance_json(row) for row in WorkflowService.list_instances(g.access_context)]})


@api_bp.post("/instances")
@require_api("workflows.write")
def create_instance():
    payload = request.get_json(silent=True) or {}
    try:
        row = WorkflowService.start(
            g.access_context,
            entity_type=payload.get("entity_type", "external_item"),
            entity_id=payload.get("entity_id", ""),
            title=payload.get("title", "Workflow item"),
            amount=payload.get("amount"),
            currency=payload.get("currency") or _base_currency(g.access_context),
            source_module=payload.get("source_module", "api"),
            metadata=payload.get("metadata") or {},
            definition_id=payload.get("workflow_definition_id"),
            originator_user_id=g.access_context.user_id,
            create_post_action=False,
        )
        return jsonify(_instance_json(row)), 201
    except (WorkflowError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.get("/actions")
@require_api("workflows.read")
def actions():
    rows = WorkflowService.open_actions(g.access_context)
    return jsonify(
        {
            "actions": [
                {
                    "id": row.id,
                    "workflow_instance_id": row.workflow_instance_id,
                    "action_type": row.action_type,
                    "title": row.title,
                    "instructions": row.instructions,
                    "assigned_user_id": row.assigned_user_id,
                    "assigned_role": row.assigned_role,
                    "status": row.status,
                    "due_date": row.due_date.isoformat() if row.due_date else None,
                }
                for row in rows
            ]
        }
    )


@api_bp.post("/actions/<action_id>/decision")
@require_api()
def action_decision(action_id):
    payload = request.get_json(silent=True) or {}
    try:
        action = db.session.get(UserAction, action_id)
        adapter = _adapter_for_action(action)
        if adapter:
            row = adapter.complete_action(
                g.access_context,
                action_id,
                decision=payload.get("decision", "approve"),
                comments=payload.get("comments"),
            )
        else:
            row = WorkflowService.complete_action(
                g.access_context,
                action_id,
                decision=payload.get("decision", "approve"),
                comments=payload.get("comments"),
            )
        return jsonify(_instance_json(row))
    except (WorkflowError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/actions/<action_id>/revise")
@require_api()
def revise_action(action_id):
    payload = request.get_json(silent=True) or {}
    try:
        action = db.session.get(UserAction, action_id)
        adapter = _adapter_for_action(action)
        if not adapter or not getattr(adapter, "supports_revision", False):
            raise WorkflowError("This workflow item does not support controlled revision")
        replacement = adapter.revise_action(
            g.access_context,
            action_id,
            payload,
            channel="api",
        )
        return jsonify(
            {
                "replacement": _instance_json(replacement),
                "replaces_workflow_instance_id": (replacement.metadata_json or {}).get(
                    "replaces_workflow_instance_id"
                ),
            }
        ), 201
    except (WorkflowError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.post("/actions/<action_id>/post")
@require_api("workflows.post")
def post_action(action_id):
    payload = request.get_json(silent=True) or {}
    try:
        action = db.session.get(UserAction, action_id)
        adapter = _adapter_for_action(action)
        if not adapter:
            raise WorkflowError("No posting adapter is registered for this workflow item")
        row = adapter.post_action(
            g.access_context,
            action_id,
            payload,
            channel="api",
        )
        return jsonify(adapter.api_result(row))
    except (WorkflowError, PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
