from ledgerone.modules.sales import credit_models, models, order_models, quote_models  # noqa: F401
from ledgerone.modules.sales.api import api_bp
from ledgerone.modules.sales.credit_api import api_bp as credit_api_bp
from ledgerone.modules.sales.credit_routes import bp as credit_bp
from ledgerone.modules.sales.order_api import api_bp as order_api_bp
from ledgerone.modules.sales.order_routes import bp as order_bp
from ledgerone.modules.sales.pdf_api import api_bp as pdf_api_bp
from ledgerone.modules.sales.pdf_routes import bp as pdf_bp
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
    app.register_blueprint(order_bp)
    app.register_blueprint(order_api_bp)
    app.register_blueprint(pdf_bp)
    app.register_blueprint(pdf_api_bp)
