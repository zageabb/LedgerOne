from io import BytesIO

from flask import Blueprint, g, jsonify, send_file

from ledgerone.security import require_api
from ledgerone.services.pdf_documents import FinancialDocumentPdfService

api_bp = Blueprint("sales_pdf_api", __name__, url_prefix="/api/v1/sales/invoices")


@api_bp.get("/<invoice_id>/pdf")
@require_api("sales.read")
def invoice_pdf(invoice_id):
    try:
        payload, filename = FinancialDocumentPdfService.sales_invoice(g.access_context, invoice_id)
        return send_file(
            BytesIO(payload),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
