from .invoice_pdf import install_compliant_sales_invoice_renderer
from .routes import bp


def register(app):
    install_compliant_sales_invoice_renderer()
    app.register_blueprint(bp)
