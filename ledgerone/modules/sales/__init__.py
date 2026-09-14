from ledgerone.modules.sales import credit_models, models, quote_models  # noqa: F401
from ledgerone.modules.sales.api import api_bp
from ledgerone.modules.sales.credit_api import api_bp as credit_api_bp
from ledgerone.modules.sales.credit_routes import bp as credit_bp
from ledgerone.modules.sales.quote_api import api_bp as quote_api_bp
from ledgerone.modules.sales.quote_routes import bp as quote_bp
from ledgerone.modules.sales.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(credit_bp)
    app.register_blueprint(credit_api_bp)
    app.register_blueprint(quote_bp)
    app.register_blueprint(quote_api_bp)
