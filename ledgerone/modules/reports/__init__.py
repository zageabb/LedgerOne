from ledgerone.modules.reports.api import api_bp
from ledgerone.modules.reports.control_accounts import api_bp as control_accounts_api_bp
from ledgerone.modules.reports.control_accounts import bp as control_accounts_bp
from ledgerone.modules.reports.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(control_accounts_bp)
    app.register_blueprint(control_accounts_api_bp)
