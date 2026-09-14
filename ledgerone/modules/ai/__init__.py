from ledgerone.modules.ai import models  # noqa: F401
from ledgerone.modules.ai.api import api_bp
from ledgerone.modules.ai.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
