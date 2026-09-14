from ledgerone.modules.auth.api import api_bp
from ledgerone.modules.auth.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
