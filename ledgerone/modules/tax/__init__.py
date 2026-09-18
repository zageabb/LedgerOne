from ledgerone.modules.tax import models  # noqa: F401
from ledgerone.modules.tax.api import api_bp
from ledgerone.modules.tax.immutability import install_vat_return_immutability_guard
from ledgerone.modules.tax.routes import bp
from ledgerone.modules.tax.services import TaxService


def register(app):
    install_vat_return_immutability_guard()
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)


def seed_defaults(organisation_id: str):
    TaxService.seed_defaults(organisation_id)
