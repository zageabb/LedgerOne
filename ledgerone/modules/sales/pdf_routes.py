from io import BytesIO

from flask import Blueprint, flash, redirect, send_file, url_for
from flask_login import login_required

from ledgerone.security import browser_context, require_module
from ledgerone.services.pdf_documents import FinancialDocumentPdfService

bp = Blueprint("sales_pdf", __name__, url_prefix="/sales/invoices")


@bp.get("/<invoice_id>/pdf")
@login_required
@require_module("sales")
def invoice_pdf(invoice_id):
    context = browser_context()
    try:
        payload, filename = FinancialDocumentPdfService.sales_invoice(context, invoice_id)
        return send_file(
            BytesIO(payload),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except (ValueError, PermissionError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("sales.index"))
