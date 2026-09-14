from ledgerone.modules.ledger.api import api_bp
from ledgerone.modules.ledger.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
