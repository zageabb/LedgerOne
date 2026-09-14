from io import BytesIO

from flask import Blueprint, g, jsonify, send_file

from ledgerone.security import require_api
from ledgerone.services.pdf_documents import FinancialDocumentPdfService

api_bp = Blueprint("purchases_pdf_api", __name__, url_prefix="/api/v1/purchases/bills")


@api_bp.get("/<bill_id>/pdf")
@require_api("purchases.read")
def bill_pdf(bill_id):
    try:
        payload, filename = FinancialDocumentPdfService.purchase_bill(g.access_context, bill_id)
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
