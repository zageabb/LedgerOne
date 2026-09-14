from decimal import Decimal

from flask import Blueprint, render_template
from flask_login import login_required

from ledgerone.models.ledger import Journal
from ledgerone.security import browser_context
from ledgerone.services.ledger import LedgerService

bp = Blueprint("core", __name__)


@bp.get("/")
@login_required
def dashboard():
    context = browser_context()
    trial_balance = LedgerService.trial_balance(context)
    assets = sum((row["balance"] for row in trial_balance if row["account_type"] == "asset"), Decimal("0"))
    liabilities = -sum((row["balance"] for row in trial_balance if row["account_type"] == "liability"), Decimal("0"))
    income = -sum((row["balance"] for row in trial_balance if row["account_type"] == "income"), Decimal("0"))
    expenses = sum((row["balance"] for row in trial_balance if row["account_type"] == "expense"), Decimal("0"))
    recent_journals = (
        Journal.query.filter_by(organisation_id=context.organisation_id, status="posted")
        .order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        .limit(8)
        .all()
    )
    return render_template(
        "core/dashboard.html",
        assets=assets,
        liabilities=liabilities,
        income=income,
        expenses=expenses,
        recent_journals=recent_journals,
    )
