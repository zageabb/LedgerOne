from datetime import date

import click
from flask import request
from flask_login import current_user

from ledgerone.module_registry import module_registry
from ledgerone.modules.workflows import models  # noqa: F401
from ledgerone.modules.workflows.api import api_bp
from ledgerone.modules.workflows.routes import bp
from ledgerone.modules.workflows.services import RecurringTransactionService
from ledgerone.security import browser_context
from ledgerone.services.context import AccessContext


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def generate_due_work_items_once_daily():
        if not app.config.get("WORKFLOW_AUTO_GENERATE_DUE", True):
            return None
        # Generation is an unrelated background-style housekeeping mutation. Never let
        # a POST/PUT/PATCH/DELETE request create work before that request's own security
        # and validation have completed (for example, before CSRF rejection).
        if request.method not in {"GET", "HEAD"}:
            return None
        if request.path.startswith("/static/") or not current_user.is_authenticated:
            return None
        context = browser_context()
        if not context or not module_registry.is_enabled(context.organisation_id, "workflows"):
            return None
        system_context = AccessContext.system(context.organisation_id)
        RecurringTransactionService.generate_due_once_per_day(
            system_context,
            through_date=date.today(),
        )
        return None

    @app.cli.command("generate-recurring-transactions")
    @click.option("--through-date", default=None, help="Generate through YYYY-MM-DD; defaults to today.")
    def generate_recurring_transactions(through_date):
        """Generate due recurring work items without posting them."""
        from ledgerone.models.core import Organisation

        target_date = date.fromisoformat(through_date) if through_date else date.today()
        total = 0
        for organisation in Organisation.query.order_by(Organisation.name.asc()).all():
            if not module_registry.is_enabled(organisation.id, "workflows"):
                continue
            rows = RecurringTransactionService.generate_due(
                AccessContext.system(organisation.id),
                through_date=target_date,
            )
            total += len(rows)
        click.echo(f"Generated {total} recurring work item(s) through {target_date.isoformat()}.")
