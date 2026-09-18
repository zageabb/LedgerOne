from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.services.audit_trace import AuditTraceService
from ledgerone.services.context import AccessContext
from ledgerone.services.pdf_documents import (
    FinancialDocumentPdfService,
    _audit_appendix,
    _money,
    _party_block,
    _quantity,
    _safe_filename,
    _text,
)

from .services import OrganisationProfileService


_INSTALLED = False


def _date_value(value, fallback: date) -> date:
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            pass
    return fallback


def _vat_rate_label(line) -> str:
    tax_code = getattr(line, "tax_code", None)
    if tax_code is None:
        return "—"
    treatment = (getattr(tax_code, "treatment", "") or "").lower()
    if treatment == "exempt":
        return "Exempt"
    if treatment == "out_of_scope":
        return "Outside scope"
    rate = Decimal(str(getattr(tax_code, "rate_percent", 0) or 0))
    text = f"{rate:.4f}".rstrip("0").rstrip(".")
    return f"{text or '0'}%"


def _supplier_story(profile: dict, styles) -> list:
    rows = [Paragraph(f"<b>{_text(profile.get('registered_name'))}</b>", styles["BodyText"])]
    trading_name = profile.get("trading_name")
    if trading_name and trading_name != profile.get("registered_name"):
        rows.append(Paragraph(f"Trading as {_text(trading_name)}", styles["BodyText"]))
    rows.extend(Paragraph(_text(line), styles["BodyText"]) for line in OrganisationProfileService.address_lines(profile))
    if profile.get("email"):
        rows.append(Paragraph(_text(profile["email"]), styles["BodyText"]))
    if profile.get("phone"):
        rows.append(Paragraph(_text(profile["phone"]), styles["BodyText"]))
    if profile.get("website"):
        rows.append(Paragraph(_text(profile["website"]), styles["BodyText"]))
    if profile.get("company_number"):
        rows.append(Paragraph(f"Company no: {_text(profile['company_number'])}", styles["BodyText"]))
    if profile.get("is_vat_registered") and profile.get("vat_registration_number"):
        rows.append(Paragraph(f"VAT registration no: {_text(profile['vat_registration_number'])}", styles["BodyText"]))
    return rows


def render_sales_invoice(context: AccessContext, invoice_id: str) -> tuple[bytes, str]:
    from ledgerone.modules.sales.models import SalesInvoice

    if not context.can("sales.read"):
        raise PermissionError("sales.read")
    invoice = db.session.get(SalesInvoice, invoice_id)
    if not invoice or invoice.organisation_id != context.organisation_id:
        raise ValueError("Invoice not found")
    organisation = db.session.get(Organisation, context.organisation_id)
    profile = OrganisationProfileService.get(context.organisation_id)

    is_vat_invoice = bool(profile.get("is_vat_registered"))
    if is_vat_invoice:
        missing = OrganisationProfileService.vat_invoice_readiness(
            context.organisation_id,
            customer_address=invoice.customer.address,
        )
        if missing:
            raise ValueError(
                "VAT invoice cannot be generated until these details are completed: "
                + ", ".join(missing)
            )
        if invoice.currency.upper() != "GBP":
            raise ValueError("UK VAT invoice VAT totals must be shown in sterling")

    metadata = invoice.metadata_json if isinstance(invoice.metadata_json, dict) else {}
    tax_point = invoice.tax_point or invoice.invoice_date
    issue_date = _date_value(metadata.get("issue_date"), invoice.invoice_date)
    trace = AuditTraceService.build(context, "sales_invoice", invoice.id)

    buffer = BytesIO()
    title = "VAT Invoice" if is_vat_invoice else "Sales Invoice"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{title} {invoice.invoice_number}",
        author=profile.get("registered_name") or organisation.name,
    )
    styles = getSampleStyleSheet()
    right = ParagraphStyle("Right", parent=styles["BodyText"], alignment=TA_RIGHT)
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, leading=10)

    story = [
        Paragraph(_text(profile.get("registered_name") or organisation.name), styles["Heading2"]),
        Paragraph(_text(title), styles["Title"]),
        Spacer(1, 3 * mm),
    ]

    identity_table = Table(
        [[_supplier_story(profile, styles), [
            Paragraph("<b>Invoice number</b>", styles["BodyText"]),
            Paragraph(_text(invoice.invoice_number), right),
            Paragraph("<b>Tax point / supply date</b>", styles["BodyText"]),
            Paragraph(tax_point.strftime("%d %b %Y"), right),
            Paragraph("<b>Issue date</b>", styles["BodyText"]),
            Paragraph(issue_date.strftime("%d %b %Y"), right),
            Paragraph("<b>Due date</b>", styles["BodyText"]),
            Paragraph(invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "—", right),
        ]]],
        colWidths=[92 * mm, 82 * mm],
    )
    identity_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([identity_table, Spacer(1, 7 * mm)])

    story.append(Paragraph("<b>Customer</b>", styles["BodyText"]))
    story.extend(
        _party_block(
            invoice.customer.name,
            invoice.customer.address,
            invoice.customer.email,
            invoice.customer.phone,
            invoice.customer.tax_id,
        )
    )
    story.append(Spacer(1, 7 * mm))

    table_rows = [[
        Paragraph("<b>Description</b>", small),
        Paragraph("<b>Qty / extent</b>", small),
        Paragraph("<b>Unit price</b>", small),
        Paragraph("<b>VAT rate</b>", small),
        Paragraph("<b>Net</b>", small),
        Paragraph("<b>VAT</b>", small),
        Paragraph("<b>Total</b>", small),
    ]]
    for line in invoice.lines:
        line_total = line.net_amount + line.tax_amount
        table_rows.append([
            Paragraph(_text(line.description), small),
            Paragraph(_quantity(line.quantity), right),
            Paragraph(_money(invoice.currency, line.unit_price), right),
            Paragraph(_text(_vat_rate_label(line)), right),
            Paragraph(_money(invoice.currency, line.net_amount), right),
            Paragraph(_money("GBP" if is_vat_invoice else invoice.currency, line.tax_amount), right),
            Paragraph(_money(invoice.currency, line_total), right),
        ])

    line_table = Table(
        table_rows,
        colWidths=[49 * mm, 18 * mm, 23 * mm, 18 * mm, 22 * mm, 20 * mm, 24 * mm],
        repeatRows=1,
    )
    line_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([line_table, Spacer(1, 6 * mm)])

    vat_label = "VAT total (GBP)" if is_vat_invoice else "Tax"
    totals = Table(
        [
            [Paragraph("Net total", styles["BodyText"]), Paragraph(_money(invoice.currency, invoice.subtotal), right)],
            [Paragraph(vat_label, styles["BodyText"]), Paragraph(_money("GBP" if is_vat_invoice else invoice.currency, invoice.tax_total), right)],
            [Paragraph("<b>Total payable</b>", styles["BodyText"]), Paragraph(f"<b>{_money(invoice.currency, invoice.total)}</b>", right)],
        ],
        colWidths=[45 * mm, 45 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([totals, Spacer(1, 8 * mm)])

    if is_vat_invoice:
        story.append(
            Paragraph(
                "This document is a UK VAT invoice. The VAT total above is expressed in sterling.",
                small,
            )
        )
    story.append(Paragraph("Generated by LedgerOne from the recorded accounting document.", small))
    story.extend(_audit_appendix(trace, styles, right, small))

    doc.build(story)
    return buffer.getvalue(), _safe_filename("invoice", invoice.invoice_number)


def install_compliant_sales_invoice_renderer() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    FinancialDocumentPdfService.sales_invoice = staticmethod(render_sales_invoice)
    _INSTALLED = True
