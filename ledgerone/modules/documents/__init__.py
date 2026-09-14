from ledgerone.modules.documents import models  # noqa: F401
from ledgerone.modules.documents.api import api_bp
from ledgerone.modules.documents.routes import bp


def register(app):
    app.register_blueprint(bp)
    app.register_blueprint(api_bp)
