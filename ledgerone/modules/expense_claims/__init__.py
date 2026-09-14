from ledgerone.modules.expense_claims import models  # noqa: F401
from ledgerone.modules.expense_claims.api import api_bp
from ledgerone.modules.expense_claims.routes import bp
from ledgerone.modules.expense_claims.services import ExpenseClaimService


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)


def seed_defaults(organisation_id: str):
    ExpenseClaimService.seed_defaults(organisation_id)
