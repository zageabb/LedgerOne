from ledgerone.modules.settings.api import api_bp
from ledgerone.modules.settings.numbering_api import api_bp as numbering_api_bp
from ledgerone.modules.settings.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(numbering_api_bp)
