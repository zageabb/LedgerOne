from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.services.context import AccessContext


def _text(value) -> str:
    return escape(str(value or ""))


def _money(currency: str, value) -> str:
    return f"{currency} {value:.2f}"


def _quantity(value) -> str:
    text = f"{value:.4f}"
    return text.rstrip("0").rstrip(".") or "0"


def _address_lines(address) -> list[str]:
    if not isinstance(address, dict):
        return []
    keys = (
        "line1",
        "line2",
        "line3",
        "city",
        "town",
        "county",
        "region",
        "postcode",
        "postal_code",
        "country",
    )
    lines = []
    seen = set()
    for key in keys:
        value = str(address.get(key) or "").strip()
        if value and value.lower() not in seen:
            lines.append(value)
            seen.add(value.lower())
    return lines


def _party_block(name: str, address, email: str | None, phone: str | None, tax_id: str | None):
    styles = getSampleStyleSheet()
    rows = [Paragraph(f"<b>{_text(name)}</b>", styles["BodyText"])]
    rows.extend(Paragraph(_text(line), styles["BodyText"]) for line in _address_lines(address))
    if email:
        rows.append(Paragraph(_text(email), styles["BodyText"]))
    if phone:
        rows.append(Paragraph(_text(phone), styles["BodyText"]))
    if tax_id:
        rows.append(Paragraph(f"Tax ID: {_text(tax_id)}", styles["BodyText"]))
    return rows


def _document_pdf(
    *,
    organisation: Organisation,
    title: str,
    number_label: str,
    number: str,
    document_date,
    due_date,
    status: str,
    party_label: str,
    party_name: str,
    party_address,
    party_email: str | None,
    party_phone: str | None,
    party_tax_id: str | None,
    currency: str,
    lines,
    subtotal,
    tax_total,
    total,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{title} {number}",
        author=organisation.name,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.spaceAfter = 4
    right = ParagraphStyle("Right", parent=styles["BodyText"], alignment=TA_RIGHT)
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, leading=10)

    story = [
        Paragraph(_text(organisation.name), styles["Heading2"]),
        Paragraph(_text(title), title_style),
        Spacer(1, 4 * mm),
    ]

    meta = Table(
        [
            [Paragraph(f"<b>{_text(number_label)}</b>", styles["BodyText"]), Paragraph(_text(number), right)],
            [Paragraph("<b>Date</b>", styles["BodyText"]), Paragraph(document_date.strftime("%d %b %Y"), right)],
            [Paragraph("<b>Due date</b>", styles["BodyText"]), Paragraph(due_date.strftime("%d %b %Y") if due_date else "—", right)],
            [Paragraph("<b>Status</b>", styles["BodyText"]), Paragraph(_text(status.replace("_", " ").title()), right)],
        ],
        colWidths=[45 * mm, 50 * mm],
        hAlign="RIGHT",
    )
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(meta)
    story.append(Spacer(1, 7 * mm))
    story.append(Paragraph(f"<b>{_text(party_label)}</b>", styles["BodyText"]))
    story.extend(_party_block(party_name, party_address, party_email, party_phone, party_tax_id))
    story.append(Spacer(1, 8 * mm))

    table_rows = [[
        Paragraph("<b>Description</b>", small),
        Paragraph("<b>Qty</b>", small),
        Paragraph("<b>Unit</b>", small),
        Paragraph("<b>Net</b>", small),
        Paragraph("<b>Tax</b>", small),
        Paragraph("<b>Total</b>", small),
    ]]
    for line in lines:
        line_total = line.net_amount + line.tax_amount
        description = line.description
        if getattr(line, "tax_code", None):
            description = f"{description} · {line.tax_code.code}"
        table_rows.append([
            Paragraph(_text(description), small),
            Paragraph(_quantity(line.quantity), right),
            Paragraph(_money(currency, line.unit_price), right),
            Paragraph(_money(currency, line.net_amount), right),
            Paragraph(_money(currency, line.tax_amount), right),
            Paragraph(_money(currency, line_total), right),
        ])

    line_table = Table(
        table_rows,
        colWidths=[66 * mm, 13 * mm, 25 * mm, 25 * mm, 22 * mm, 27 * mm],
        repeatRows=1,
    )
    line_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 6 * mm))

    totals = Table(
        [
            [Paragraph("Subtotal", styles["BodyText"]), Paragraph(_money(currency, subtotal), right)],
            [Paragraph("Tax", styles["BodyText"]), Paragraph(_money(currency, tax_total), right)],
            [Paragraph("<b>Total</b>", styles["BodyText"]), Paragraph(f"<b>{_money(currency, total)}</b>", right)],
        ],
        colWidths=[35 * mm, 45 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals)
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("Generated by LedgerOne from the recorded accounting document.", small))

    doc.build(story)
    return buffer.getvalue()


class FinancialDocumentPdfService:
    @staticmethod
    def sales_invoice(context: AccessContext, invoice_id: str) -> tuple[bytes, str]:
        if not context.can("sales.read"):
            raise PermissionError("sales.read")
        invoice = db.session.get(SalesInvoice, invoice_id)
        if not invoice or invoice.organisation_id != context.organisation_id:
            raise ValueError("Invoice not found")
        organisation = db.session.get(Organisation, context.organisation_id)
        pdf = _document_pdf(
            organisation=organisation,
            title="Sales Invoice",
            number_label="Invoice number",
            number=invoice.invoice_number,
            document_date=invoice.invoice_date,
            due_date=invoice.due_date,
            status=invoice.status,
            party_label="Bill to",
            party_name=invoice.customer.name,
            party_address=invoice.customer.address,
            party_email=invoice.customer.email,
            party_phone=invoice.customer.phone,
            party_tax_id=invoice.customer.tax_id,
            currency=invoice.currency,
            lines=invoice.lines,
            subtotal=invoice.subtotal,
            tax_total=invoice.tax_total,
            total=invoice.total,
        )
        return pdf, f"invoice-{invoice.invoice_number}.pdf"

    @staticmethod
    def purchase_bill(context: AccessContext, bill_id: str) -> tuple[bytes, str]:
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        bill = db.session.get(PurchaseBill, bill_id)
        if not bill or bill.organisation_id != context.organisation_id:
            raise ValueError("Bill not found")
        organisation = db.session.get(Organisation, context.organisation_id)
        pdf = _document_pdf(
            organisation=organisation,
            title="Purchase Bill",
            number_label="Bill number",
            number=bill.bill_number,
            document_date=bill.bill_date,
            due_date=bill.due_date,
            status=bill.status,
            party_label="Supplier",
            party_name=bill.supplier.name,
            party_address=bill.supplier.address,
            party_email=bill.supplier.email,
            party_phone=bill.supplier.phone,
            party_tax_id=bill.supplier.tax_id,
            currency=bill.currency,
            lines=bill.lines,
            subtotal=bill.subtotal,
            tax_total=bill.tax_total,
            total=bill.total,
        )
        return pdf, f"bill-{bill.bill_number}.pdf"
