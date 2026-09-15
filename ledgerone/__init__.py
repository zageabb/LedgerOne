from __future__ import annotations

from flask import Flask, request, session
from flask_login import current_user
from dotenv import load_dotenv


def create_app(config_overrides: dict | None = None):
    """Create and configure a LedgerOne Flask application.

    ``config_overrides`` is intentionally supported so tests, workers and future
    deployment wrappers can create isolated app instances without mutating global
    environment variables.
    """
    load_dotenv()

    from ledgerone.config import get_config
    from ledgerone.extensions import csrf, db, login_manager, migrate
    from ledgerone.module_registry import module_registry
    from ledgerone.models import User
    from ledgerone.services.control_accounts import (
        install_control_account_service_guards,
        seed_all_control_account_metadata,
    )
    from ledgerone.services.currency import install_currency_service_guards

    # Currency only depends on the core ledger models, so it is safe to install before
    # module discovery. Cross-module control-account scopes are installed after every
    # module package has finished importing to avoid circular package initialisation.
    install_currency_service_guards()

    app = Flask(__name__)
    app.config.from_object(get_config())
    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, user_id)

    module_registry.discover()
    install_control_account_service_guards()
    module_registry.register_blueprints(app)

    @app.before_request
    def secure_browser_request():
        session.permanent = True
        if (
            app.config.get("WTF_CSRF_ENABLED", True)
            and request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}
            and not request.path.startswith("/api/")
        ):
            csrf.protect()

    @app.context_processor
    def inject_ledgerone_context():
        from ledgerone.models.core import Membership, Organisation
        from ledgerone.security import browser_context

        context = browser_context() if current_user.is_authenticated else None
        organisation = (
            db.session.get(Organisation, context.organisation_id)
            if context and context.organisation_id
            else None
        )
        enabled_modules = []
        if organisation:
            mode = getattr(current_user, "ui_mode", "home")
            for manifest in module_registry.manifests:
                visible = manifest.home_visible if mode == "home" else manifest.professional_visible
                if visible and module_registry.is_enabled(organisation.id, manifest.id):
                    enabled_modules.append(manifest)
        memberships = []
        if current_user.is_authenticated:
            memberships = (
                Membership.query.filter_by(user_id=current_user.id, is_active=True)
                .order_by(Membership.created_at.asc())
                .all()
            )
        return {
            "ledgerone_modules": enabled_modules,
            "current_organisation": organisation,
            "current_memberships": memberships,
            "ui_mode": getattr(current_user, "ui_mode", "home") if current_user.is_authenticated else "home",
        }

    with app.app_context():
        from ledgerone.bootstrap import bootstrap_database

        bootstrap_database(
            create_schema=app.config.get("AUTO_CREATE_SCHEMA", True),
            seed_defaults=app.config.get("AUTO_SEED_DEFAULTS", True),
        )
        seed_all_control_account_metadata()

    return app
