from ledgerone.modules.core.api import api_bp
from ledgerone.modules.core.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
