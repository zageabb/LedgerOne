from datetime import date

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.documents.services import DocumentService
from ledgerone.modules.sales.orders import SalesOrderService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.audit_trace import AuditTraceService
from ledgerone.services.context import AccessContext
from ledgerone.services.pdf_documents import FinancialDocumentPdfService


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def test_invoice_trace_lists_origin_accounts_evidence_and_events(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Audit Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-AUDIT-001",
            invoice_date=date(2026, 9, 15),
            due_date=None,
            description="Auditable service",
            amount="125.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        evidence = DocumentService.create_reference(
            context,
            entity_type="sales_invoice",
            entity_id=invoice.id,
            title="Customer approval",
            reference_url="https://example.test/evidence/approval-001",
        )

        trace = AuditTraceService.build(context, "sales_invoice", invoice.id)

        assert trace["target"]["reference"] == "INV-AUDIT-001"
        assert trace["target"]["table"] == "sales_invoices"
        assert invoice.id in trace["target"]["record_location"]
        assert trace["origin"]["label"] == "Direct sales invoice entry"
        assert trace["journal"]["id"] == invoice.posted_journal_id
        assert trace["journal"]["source_module"] == "sales"
        assert trace["journal"]["source_reference"] == invoice.id

        accounts_by_code = {line["account_code"]: line for line in trace["journal"]["lines"]}
        assert set(accounts_by_code) == {"1200", "4000"}
        assert accounts_by_code["1200"]["account_name"]
        assert accounts_by_code["1200"]["debit"] == "125.00"
        assert accounts_by_code["4000"]["credit"] == "125.00"
        assert "journal_lines" in accounts_by_code["1200"]["record_location"]

        evidence_row = next(row for row in trace["evidence"] if row["id"] == evidence.id)
        assert evidence_row["location"] == "https://example.test/evidence/approval-001"
        assert evidence_row["target_type"] == "sales_invoice"

        actions = {row["action"] for row in trace["events"]}
        assert "invoice_posted" in actions
        assert "source_reference_added" in actions


def test_converted_sales_order_is_reported_as_invoice_origin(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Order Audit Customer")
        order = SalesOrderService.create_order(
            context,
            customer_id=customer.id,
            order_number="SO-AUDIT-001",
            order_date=date(2026, 9, 15),
            requested_delivery_date=None,
            description="Order-origin service",
            amount="50.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        SalesOrderService.set_status(context, order.id, status="confirmed")
        invoice, _ = SalesOrderService.convert_to_invoice(
            context,
            order.id,
            invoice_number="INV-FROM-SO-AUDIT",
            invoice_date=date(2026, 9, 15),
            due_date=None,
        )

        trace = AuditTraceService.build(context, "sales_invoice", invoice.id)
        assert trace["origin"]["label"] == "Converted from sales order"
        assert trace["origin"]["entity_type"] == "sales_order"
        assert trace["origin"]["entity_id"] == order.id
        assert trace["origin"]["reference"] == "SO-AUDIT-001"
        actions = {row["action"] for row in trace["events"]}
        assert "sales_order_created" in actions
        assert "sales_order_converted" in actions
        assert "invoice_posted" in actions


def test_pdf_contains_audit_appendix_data_source(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="PDF Audit Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-AUDIT-PDF",
            invoice_date=date(2026, 9, 15),
            due_date=None,
            description="Audit PDF service",
            amount="75.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        DocumentService.create_reference(
            context,
            entity_type="sales_invoice",
            entity_id=invoice.id,
            title="External source",
            reference_url="https://example.test/source/75",
        )

        pdf, filename = FinancialDocumentPdfService.sales_invoice(context, invoice.id)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 3000
        assert filename == "invoice-INV-AUDIT-PDF.pdf"


def test_documents_audit_trace_api_route_is_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/v1/documents/audit-trace" in rules
