from ledgerone.modules.purchases import models  # noqa: F401
from ledgerone.modules.purchases.api import api_bp
from ledgerone.modules.purchases.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
