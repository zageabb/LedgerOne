from ledgerone.modules.ledger.api import api_bp
from ledgerone.modules.ledger.control_api import control_api_bp
from ledgerone.modules.ledger.period_api import period_api_bp
from ledgerone.modules.ledger.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(control_api_bp)
    app.register_blueprint(period_api_bp)
