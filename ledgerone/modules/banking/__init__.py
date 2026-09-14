from ledgerone.modules.banking import models  # noqa: F401
from ledgerone.modules.banking.api import api_bp
from ledgerone.modules.banking.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
