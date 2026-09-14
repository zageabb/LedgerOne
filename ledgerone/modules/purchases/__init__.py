from ledgerone.modules.purchases import credit_models, models  # noqa: F401
from ledgerone.modules.purchases.api import api_bp
from ledgerone.modules.purchases.credit_api import api_bp as credit_api_bp
from ledgerone.modules.purchases.credit_routes import bp as credit_bp
from ledgerone.modules.purchases.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(credit_bp)
    app.register_blueprint(credit_api_bp)
