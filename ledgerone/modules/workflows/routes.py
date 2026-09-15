from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.module_registry import module_registry
from ledgerone.modules.workflows.models import ScheduledTransaction, UserAction
from ledgerone.modules.workflows.posting import can_post_action
from ledgerone.modules.workflows.services import (
    RecurringTransactionService,
    WorkflowError,
    WorkflowService,
)
from ledgerone.security import browser_context, require_module

bp = Blueprint("workflows", __name__, url_prefix="/workflows")


def _optional_date(value: str | None):
    return date.fromisoformat(value) if value else None


def _adapter_for_action(action: UserAction | None):
    if not action or not action.workflow_instance:
        return None
    return module_registry.workflow_adapter(action.workflow_instance.entity_type)


@bp.route("/", methods=["GET", "POST"])
@login_required
@require_module("workflows")
def index():
    context = browser_context()
    organisation = db.session.get(Organisation, context.organisation_id)
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create_template":
                RecurringTransactionService.create_template(
                    context,
                    name=request.form.get("name", ""),
                    description=request.form.get("description") or None,
                    transaction_type=request.form.get("transaction_type", "expense"),
                    amount_mode=request.form.get("amount_mode", "expected"),
                    expected_amount=request.form.get("expected_amount") or None,
                    tolerance=request.form.get("tolerance") or None,
                    currency=organisation.base_currency,
                    bank_account_id=request.form.get("bank_account_id", ""),
                    counter_account_id=request.form.get("counter_account_id", ""),
                    frequency=request.form.get("frequency", "monthly"),
                    next_run_date=date.fromisoformat(request.form.get("next_run_date") or date.today().isoformat()),
                    end_date=_optional_date(request.form.get("end_date")),
                    reference=request.form.get("reference") or None,
                    workflow_definition_id=request.form.get("workflow_definition_id") or None,
                )
                flash("Recurring transaction template created. It will generate work items, not auto-post.", "success")
            elif action == "generate_due":
                generated = RecurringTransactionService.generate_due(context, through_date=date.today())
                flash(f"Generated {len(generated)} due work item(s).", "success")
            return redirect(url_for("workflows.index"))
        except (WorkflowError, PermissionError, ValueError) as exc:
            flash(str(exc), "danger")

    accounts = [
        row
        for row in Account.query.filter_by(
            organisation_id=context.organisation_id,
            is_active=True,
        ).order_by(Account.code).all()
    ]
    settlement_accounts = [
        row for row in accounts if row.account_type in {"asset", "liability"} and not row.is_control_account
    ]
    category_accounts = [
        row
        for row in accounts
        if row.account_type in {"income", "expense", "asset", "liability"} and not row.is_control_account
    ]
    definitions = [row for row in WorkflowService.list_definitions(context) if row.is_active]
    return render_template(
        "workflows/index.html",
        templates=RecurringTransactionService.list_templates(context),
        items=RecurringTransactionService.list_items(context),
        definitions=definitions,
        settlement_accounts=settlement_accounts,
        category_accounts=category_accounts,
        frequencies=RecurringTransactionService.FREQUENCIES,
        base_currency=organisation.base_currency,
        today=date.today().isoformat(),
        can_write=context.can("workflows.write"),
        can_manage=context.can("workflows.manage"),
    )


@bp.post("/templates/<template_id>/active")
@login_required
@require_module("workflows")
def set_template_active(template_id):
    context = browser_context()
    try:
        active = request.form.get("active") == "1"
        row = RecurringTransactionService.set_template_active(context, template_id, active=active)
        flash(f"{row.name} {'enabled' if row.is_active else 'disabled'}.", "success")
    except (WorkflowError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("workflows.index"))


@bp.route("/definitions", methods=["GET", "POST"])
@login_required
@require_module("workflows")
def definitions():
    context = browser_context()
    if request.method == "POST":
        try:
            WorkflowService.create_definition(
                context,
                name=request.form.get("name", ""),
                description=request.form.get("description") or None,
                entity_type=request.form.get("entity_type") or "scheduled_transaction",
                transaction_type=request.form.get("transaction_type") or None,
                min_amount=request.form.get("min_amount") or None,
                max_amount=request.form.get("max_amount") or None,
                review_required=request.form.get("review_required") == "1",
                approval_required=request.form.get("approval_required") == "1",
                approval_role=request.form.get("approval_role") or None,
                separate_approver=request.form.get("separate_approver") == "1",
                priority=int(request.form.get("priority") or 100),
            )
            flash("Workflow rule created.", "success")
            return redirect(url_for("workflows.definitions"))
        except (WorkflowError, PermissionError, ValueError) as exc:
            flash(str(exc), "danger")
    return render_template(
        "workflows/definitions.html",
        definitions=WorkflowService.list_definitions(context),
        can_manage=context.can("workflows.manage"),
    )


@bp.post("/definitions/<definition_id>/active")
@login_required
@require_module("workflows")
def set_definition_active(definition_id):
    context = browser_context()
    try:
        active = request.form.get("active") == "1"
        row = WorkflowService.set_definition_active(context, definition_id, active=active)
        flash(f"{row.name} {'enabled' if row.is_active else 'disabled'}.", "success")
    except (WorkflowError, PermissionError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("workflows.definitions"))


@bp.get("/actions")
@login_required
@require_module("workflows")
def actions():
    context = browser_context()
    rows = WorkflowService.open_actions(context)
    item_map = {}
    post_access = {}
    for action in rows:
        instance = action.workflow_instance
        if instance.entity_type == "scheduled_transaction":
            item_map[action.id] = db.session.get(ScheduledTransaction, instance.entity_id)
        post_access[action.id] = can_post_action(context, action)
    return render_template(
        "workflows/actions.html",
        actions=rows,
        recent_actions=WorkflowService.recent_actions(context),
        action_items=item_map,
        post_access=post_access,
        can_review=context.can("workflows.review"),
        can_approve=context.can("workflows.approve"),
        today=date.today().isoformat(),
    )


@bp.post("/actions/<action_id>/decision")
@login_required
@require_module("workflows")
def action_decision(action_id):
    context = browser_context()
    try:
        action = db.session.get(UserAction, action_id)
        adapter = _adapter_for_action(action)
        if adapter:
            instance = adapter.complete_action(
                context,
                action_id,
                decision=request.form.get("decision") or "approve",
                comments=request.form.get("comments") or None,
            )
        else:
            instance = WorkflowService.complete_action(
                context,
                action_id,
                decision=request.form.get("decision") or "approve",
                comments=request.form.get("comments") or None,
            )
        flash(f"Action completed. Workflow is now {instance.status.replace('_', ' ')}.", "success")
    except (WorkflowError, PermissionError, ValueError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("workflows.actions"))


@bp.post("/actions/<action_id>/post")
@login_required
@require_module("workflows")
def post_action(action_id):
    context = browser_context()
    try:
        action = db.session.get(UserAction, action_id)
        adapter = _adapter_for_action(action)
        if not adapter:
            raise WorkflowError("No posting adapter is registered for this workflow item")
        row = adapter.post_action(
            context,
            action_id,
            request.form,
            channel="browser",
        )
        flash(adapter.browser_message(row), "success")
    except (WorkflowError, PermissionError, ValueError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("workflows.actions"))
