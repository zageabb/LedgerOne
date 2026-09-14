from ledgerone.modules.audit.api import api_bp
from ledgerone.modules.audit.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
