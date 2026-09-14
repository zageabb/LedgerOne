from io import BytesIO

from flask import Blueprint, flash, redirect, send_file, url_for
from flask_login import login_required

from ledgerone.security import browser_context, require_module
from ledgerone.services.pdf_documents import FinancialDocumentPdfService

bp = Blueprint("purchases_pdf", __name__, url_prefix="/purchases/bills")


@bp.get("/<bill_id>/pdf")
@login_required
@require_module("purchases")
def bill_pdf(bill_id):
    context = browser_context()
    try:
        payload, filename = FinancialDocumentPdfService.purchase_bill(context, bill_id)
        return send_file(
            BytesIO(payload),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except (ValueError, PermissionError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("purchases.index"))
