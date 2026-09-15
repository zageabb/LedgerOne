from __future__ import annotations

import json
import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.services.audit_trace import AuditTraceService
from ledgerone.services.context import AccessContext


def _text(value) -> str:
    return escape(str(value or ""))


def _money(currency: str, value) -> str:
    return f"{currency} {value:.2f}"


def _quantity(value) -> str:
    text = f"{value:.4f}"
    return text.rstrip("0").rstrip(".") or "0"


def _safe_filename(prefix: str, number: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(number or "document")).strip(".-")
    return f"{prefix}-{safe or 'document'}.pdf"


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


def _compact_json(value) -> str:
    if not value:
        return "—"
    return json.dumps(value, sort_keys=True, default=str, separators=(", ", ": "))


def _audit_appendix(trace: dict, styles, right, small) -> list:
    tiny = ParagraphStyle("AuditTiny", parent=small, fontSize=6.5, leading=8)
    heading = ParagraphStyle("AuditHeading", parent=styles["Heading2"], spaceBefore=4, spaceAfter=5)
    story = [PageBreak(), Paragraph("Audit & Provenance", styles["Title"])]
    story.append(
        Paragraph(
            "Full transaction trace from source record through journal and ledger accounts to supporting evidence and recorded audit events.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 5 * mm))

    target = trace["target"]
    origin = trace.get("origin") or {}
    record_rows = [
        ["Record type", target.get("entity_type")],
        ["Reference", target.get("reference")],
        ["Record ID", target.get("entity_id")],
        ["Database table", target.get("table")],
        ["Record location", target.get("record_location")],
        ["Status", target.get("status")],
        ["Created", target.get("created_at")],
        ["Updated", target.get("updated_at")],
        ["Origin", origin.get("label")],
        ["Source type", origin.get("entity_type")],
        ["Source reference", origin.get("reference")],
        ["Source ID", origin.get("entity_id")],
    ]
    if origin.get("ledger_account"):
        record_rows.append(["Source ledger account", origin.get("ledger_account")])
    record_table = Table(
        [[Paragraph(f"<b>{_text(label)}</b>", tiny), Paragraph(_text(value or "—"), tiny)] for label, value in record_rows],
        colWidths=[42 * mm, 132 * mm],
    )
    record_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D0D0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F4F4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([Paragraph("Record lineage", heading), record_table, Spacer(1, 5 * mm)])

    journal = trace.get("journal")
    story.append(Paragraph("Journal and ledger accounts", heading))
    if journal:
        journal_rows = [
            ["Journal ID", journal.get("id")],
            ["Journal location", journal.get("record_location")],
            ["Journal date", journal.get("date")],
            ["Reference", journal.get("reference")],
            ["Description", journal.get("description")],
            ["Source module", journal.get("source_module")],
            ["Source record", journal.get("source_reference")],
            ["Created by", journal.get("created_by") or "System"],
            ["Created", journal.get("created_at")],
            ["Posted", journal.get("posted_at")],
            ["Reversal of", journal.get("reversal_of_id")],
            ["Total debit / credit", f"{journal.get('total_debit')} / {journal.get('total_credit')}"]
        ]
        journal_table = Table(
            [[Paragraph(f"<b>{_text(label)}</b>", tiny), Paragraph(_text(value or "—"), tiny)] for label, value in journal_rows],
            colWidths=[42 * mm, 132 * mm],
        )
        journal_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D0D0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F4F4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([journal_table, Spacer(1, 4 * mm)])

        ledger_rows = [[
            Paragraph("<b>#</b>", tiny),
            Paragraph("<b>Account</b>", tiny),
            Paragraph("<b>Type</b>", tiny),
            Paragraph("<b>Description / dimensions</b>", tiny),
            Paragraph("<b>Debit</b>", tiny),
            Paragraph("<b>Credit</b>", tiny),
            Paragraph("<b>Location</b>", tiny),
        ]]
        for line in journal.get("lines") or []:
            details = line.get("description") or ""
            if line.get("dimensions"):
                details = f"{details}\n{_compact_json(line['dimensions'])}".strip()
            ledger_rows.append([
                Paragraph(_text(line.get("line_number")), tiny),
                Paragraph(_text(f"{line.get('account_code')} · {line.get('account_name')}\n{line.get('account_id')}"), tiny),
                Paragraph(_text(line.get("account_type")), tiny),
                Paragraph(_text(details or "—"), tiny),
                Paragraph(_text(f"{line.get('currency') or ''} {line.get('debit')}"), tiny),
                Paragraph(_text(f"{line.get('currency') or ''} {line.get('credit')}"), tiny),
                Paragraph(_text(line.get("record_location")), tiny),
            ])
        ledger_table = Table(ledger_rows, colWidths=[7*mm, 38*mm, 17*mm, 43*mm, 20*mm, 20*mm, 29*mm], repeatRows=1)
        ledger_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(ledger_table)
    else:
        story.append(Paragraph("No posted journal is linked to this record.", styles["BodyText"]))
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph("Supporting evidence and location", heading))
    evidence = trace.get("evidence") or []
    if evidence:
        evidence_rows = [[
            Paragraph("<b>Added</b>", tiny),
            Paragraph("<b>Title / target</b>", tiny),
            Paragraph("<b>Type</b>", tiny),
            Paragraph("<b>Location</b>", tiny),
            Paragraph("<b>Integrity / owner</b>", tiny),
        ]]
        for row in evidence:
            integrity = f"SHA-256 {row.get('sha256')}\n{row.get('size_bytes') or 0} bytes" if row.get("sha256") else "External reference"
            if row.get("uploaded_by"):
                integrity += f"\nAdded by {row.get('uploaded_by')}"
            evidence_rows.append([
                Paragraph(_text(row.get("created_at")), tiny),
                Paragraph(_text(f"{row.get('title')}\n{row.get('target_type')} / {row.get('target_id')}"), tiny),
                Paragraph(_text(row.get("kind")), tiny),
                Paragraph(_text(row.get("location") or "—"), tiny),
                Paragraph(_text(integrity), tiny),
            ])
        evidence_table = Table(evidence_rows, colWidths=[29*mm, 38*mm, 16*mm, 52*mm, 39*mm], repeatRows=1)
        evidence_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(evidence_table)
    else:
        story.append(Paragraph("No supporting file or external evidence reference is linked to this record or its journal.", styles["BodyText"]))
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph("Full audit event listing", heading))
    events = trace.get("events") or []
    if events:
        event_rows = [[
            Paragraph("<b>Timestamp</b>", tiny),
            Paragraph("<b>Actor</b>", tiny),
            Paragraph("<b>Module / action</b>", tiny),
            Paragraph("<b>Entity</b>", tiny),
            Paragraph("<b>Recorded detail</b>", tiny),
        ]]
        for row in events:
            event_rows.append([
                Paragraph(_text(row.get("created_at")), tiny),
                Paragraph(_text(row.get("actor")), tiny),
                Paragraph(_text(f"{row.get('module_id')} / {row.get('action')}"), tiny),
                Paragraph(_text(f"{row.get('entity_type')} / {row.get('entity_id')}"), tiny),
                Paragraph(_text(_compact_json(row.get("detail"))), tiny),
            ])
        event_table = Table(event_rows, colWidths=[29*mm, 32*mm, 32*mm, 37*mm, 44*mm], repeatRows=1)
        event_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(event_table)
    else:
        story.append(Paragraph("No audit events are recorded for this trace.", styles["BodyText"]))
    return story


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
    audit_trace: dict | None = None,
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

    meta_rows = [
        [Paragraph(f"<b>{_text(number_label)}</b>", styles["BodyText"]), Paragraph(_text(number), right)],
        [Paragraph("<b>Date</b>", styles["BodyText"]), Paragraph(document_date.strftime("%d %b %Y"), right)],
        [Paragraph("<b>Due date</b>", styles["BodyText"]), Paragraph(due_date.strftime("%d %b %Y") if due_date else "—", right)],
        [Paragraph("<b>Status</b>", styles["BodyText"]), Paragraph(_text(status.replace("_", " ").title()), right)],
    ]
    if audit_trace:
        origin = audit_trace.get("origin") or {}
        journal = audit_trace.get("journal") or {}
        meta_rows.extend([
            [Paragraph("<b>Source</b>", styles["BodyText"]), Paragraph(_text(origin.get("label") or "Direct entry"), right)],
            [Paragraph("<b>Journal</b>", styles["BodyText"]), Paragraph(_text(journal.get("reference") or journal.get("id") or "—"), right)],
        ])
    meta = Table(meta_rows, colWidths=[45 * mm, 50 * mm], hAlign="RIGHT")
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

    line_table = Table(table_rows, colWidths=[62 * mm, 13 * mm, 24 * mm, 24 * mm, 22 * mm, 29 * mm], repeatRows=1)
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
    if audit_trace:
        story.extend(_audit_appendix(audit_trace, styles, right, small))

    doc.build(story)
    return buffer.getvalue()


class FinancialDocumentPdfService:
    @staticmethod
    def sales_invoice(context: AccessContext, invoice_id: str) -> tuple[bytes, str]:
        from ledgerone.modules.sales.models import SalesInvoice

        if not context.can("sales.read"):
            raise PermissionError("sales.read")
        invoice = db.session.get(SalesInvoice, invoice_id)
        if not invoice or invoice.organisation_id != context.organisation_id:
            raise ValueError("Invoice not found")
        organisation = db.session.get(Organisation, context.organisation_id)
        trace = AuditTraceService.build(context, "sales_invoice", invoice.id)
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
            audit_trace=trace,
        )
        return pdf, _safe_filename("invoice", invoice.invoice_number)

    @staticmethod
    def purchase_bill(context: AccessContext, bill_id: str) -> tuple[bytes, str]:
        from ledgerone.modules.purchases.models import PurchaseBill

        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        bill = db.session.get(PurchaseBill, bill_id)
        if not bill or bill.organisation_id != context.organisation_id:
            raise ValueError("Bill not found")
        organisation = db.session.get(Organisation, context.organisation_id)
        trace = AuditTraceService.build(context, "purchase_bill", bill.id)
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
            audit_trace=trace,
        )
        return pdf, _safe_filename("bill", bill.bill_number)
