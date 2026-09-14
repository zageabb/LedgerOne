import re

from flask import current_app
from sqlalchemy import inspect

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.models.ledger import Account
from ledgerone.module_registry import module_registry


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "ledger"


def _seed_chart(organisation_id: str):
    if Account.query.filter_by(organisation_id=organisation_id).first():
        return
    defaults = [
        ("1000", "Current Account", "asset"),
        ("1100", "Savings", "asset"),
        ("1200", "Accounts Receivable", "asset"),
        ("2000", "Credit Cards / Short-term Debt", "liability"),
        ("2100", "Accounts Payable", "liability"),
        ("3000", "Opening Balance / Equity", "equity"),
        ("4000", "Income", "income"),
        ("4100", "Other Income", "income"),
        ("5000", "Household / General Expenses", "expense"),
        ("5100", "Utilities", "expense"),
        ("5200", "Travel and Vehicle", "expense"),
        ("5300", "Food and Groceries", "expense"),
    ]
    for code, name, account_type in defaults:
        db.session.add(
            Account(
                organisation_id=organisation_id,
                code=code,
                name=name,
                account_type=account_type,
            )
        )
    db.session.commit()


def bootstrap_database(*, create_schema: bool = True, seed_defaults: bool = True):
    """Prepare a development/local database after the app and modules are loaded.

    Production deployments should normally set ``AUTO_CREATE_SCHEMA=false`` and run
    ``flask db upgrade`` before starting the web process. Keeping schema creation
    separate from seeding prevents ``db.create_all()`` from silently replacing the
    migration workflow while retaining a frictionless SQLite first run.

    When the schema does not exist yet, seeding is skipped. This is essential for
    commands such as ``flask db upgrade`` because Flask must create the app before
    Alembic can create the initial tables.
    """
    if create_schema:
        db.create_all()

    if not seed_defaults:
        return

    inspector = inspect(db.engine)
    if not inspector.has_table("users") or not inspector.has_table("organisations"):
        return

    if not User.query.first():
        user = User(
            email=current_app.config["ADMIN_EMAIL"].strip().lower(),
            name=current_app.config["ADMIN_NAME"],
            ui_mode="home",
        )
        user.set_password(current_app.config["ADMIN_PASSWORD"])
        organisation = Organisation(
            name=current_app.config["DEFAULT_ORG_NAME"],
            slug=_slugify(current_app.config["DEFAULT_ORG_NAME"]),
        )
        db.session.add_all([user, organisation])
        db.session.flush()
        db.session.add(
            Membership(
                organisation_id=organisation.id,
                user_id=user.id,
                role="owner",
                permissions=["*"],
            )
        )
        db.session.commit()

    for organisation in Organisation.query.all():
        module_registry.ensure_org_states(organisation.id)
        _seed_chart(organisation.id)
        module_registry.seed_org_defaults(organisation.id)
