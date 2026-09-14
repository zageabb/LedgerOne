from ledgerone.modules.reports.api import api_bp
from ledgerone.modules.reports.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
