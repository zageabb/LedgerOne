from ledgerone.modules.sales import credit_models, models  # noqa: F401
from ledgerone.modules.sales.api import api_bp
from ledgerone.modules.sales.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
