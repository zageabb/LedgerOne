from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.pdf_documents import FinancialDocumentPdfService


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, context, accounts


def test_invoice_and_bill_pdf_generation(app):
    with app.app_context():
        _, context, accounts = _setup()
        customer = SalesService.create_customer(
            context,
            name="PDF Customer",
            email="customer@example.test",
            phone="01234 567890",
        )
        customer.address = {
            "line1": "1 Customer Street",
            "city": "Stafford",
            "postcode": "ST16 1AA",
            "country": "United Kingdom",
        }
        supplier = PurchasesService.create_supplier(
            context,
            name="PDF Supplier",
            email="supplier@example.test",
            phone="01999 000111",
        )
        supplier.address = {
            "line1": "2 Supplier Road",
            "city": "Birmingham",
            "postcode": "B1 1AA",
            "country": "United Kingdom",
        }
        db.session.commit()

        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV/2026:001",
            invoice_date=date(2026, 9, 14),
            due_date=date(2026, 10, 14),
            description="PDF invoice service",
            amount="125.50",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="BILL/2026:001",
            bill_date=date(2026, 9, 14),
            due_date=date(2026, 10, 14),
            description="PDF purchase",
            amount="75.25",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
        )

        invoice_pdf, invoice_filename = FinancialDocumentPdfService.sales_invoice(
            context, invoice.id
        )
        bill_pdf, bill_filename = FinancialDocumentPdfService.purchase_bill(context, bill.id)

        assert invoice_pdf.startswith(b"%PDF")
        assert bill_pdf.startswith(b"%PDF")
        assert len(invoice_pdf) > 1000
        assert len(bill_pdf) > 1000
        assert invoice_filename == "invoice-INV-2026-001.pdf"
        assert bill_filename == "bill-BILL-2026-001.pdf"
        assert invoice.invoice_number == "INV/2026:001"
        assert bill.bill_number == "BILL/2026:001"
        assert customer.address["postcode"] == "ST16 1AA"
        assert supplier.address["postcode"] == "B1 1AA"


def test_pdf_service_enforces_organisation_boundary(app):
    with app.app_context():
        _, context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Boundary Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-PDF-BOUNDARY",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Boundary test",
            amount="10.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        supplier = PurchasesService.create_supplier(context, name="Boundary Supplier")
        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="BILL-PDF-BOUNDARY",
            bill_date=date(2026, 9, 14),
            due_date=None,
            description="Boundary test",
            amount="10.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
        )

        other = Organisation(
            name="Other Ledger",
            slug="other-ledger-pdf-test",
            base_currency="GBP",
            country_code="GB",
        )
        db.session.add(other)
        db.session.commit()
        other_context = AccessContext.system(other.id)

        with pytest.raises(ValueError, match="Invoice not found"):
            FinancialDocumentPdfService.sales_invoice(other_context, invoice.id)
        with pytest.raises(ValueError, match="Bill not found"):
            FinancialDocumentPdfService.purchase_bill(other_context, bill.id)


def test_pdf_routes_are_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/sales/invoices/<invoice_id>/pdf" in rules
    assert "/api/v1/sales/invoices/<invoice_id>/pdf" in rules
    assert "/purchases/bills/<bill_id>/pdf" in rules
    assert "/api/v1/purchases/bills/<bill_id>/pdf" in rules
