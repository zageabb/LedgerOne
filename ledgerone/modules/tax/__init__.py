from ledgerone.modules.tax import models  # noqa: F401
from ledgerone.modules.tax.api import api_bp
from ledgerone.modules.tax.routes import bp
from ledgerone.modules.tax.services import TaxService


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)


def seed_defaults(organisation_id: str):
    TaxService.seed_defaults(organisation_id)
