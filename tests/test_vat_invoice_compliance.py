from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.module_registry import module_registry
from ledgerone.modules.organisation_profile.invoice_pdf import _vat_rate_label
from ledgerone.modules.organisation_profile.services import OrganisationProfileService
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.tax.models import TaxCode
from ledgerone.modules.tax.services import TaxService
from ledgerone.services.context import AccessContext
from ledgerone.services.pdf_documents import FinancialDocumentPdfService


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    # VAT-document tests exercise the real optional Tax module boundary. Enable it
    # through Settings so its normal accounts, UK tax codes and control metadata are
    # seeded exactly as they are in the application.
    if not module_registry.is_enabled(organisation.id, "tax"):
        SettingsService.set_module_enabled(context, "tax", True)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, context, accounts


def _complete_profile(context):
    OrganisationProfileService.update(
        context,
        registered_name="LedgerOne Test Ltd",
        trading_name="LedgerOne Test",
        company_number="12345678",
        email="accounts@example.test",
        phone="01234 567890",
        website="https://example.test",
        address_line1="1 Test Street",
        city="Stafford",
        county="Staffordshire",
        postcode="ST16 1AA",
        country="United Kingdom",
    )
    TaxService.update_profile(
        context,
        jurisdiction="GB",
        is_vat_registered=True,
        registration_number="GB123456789",
        scheme="standard",
        return_frequency="quarterly",
    )


def test_business_profile_persists_legal_identity_and_uses_tax_profile(app):
    with app.app_context():
        _, context, _ = _setup()
        _complete_profile(context)
        profile = OrganisationProfileService.get(context.organisation_id)

        assert profile["registered_name"] == "LedgerOne Test Ltd"
        assert profile["trading_name"] == "LedgerOne Test"
        assert profile["company_number"] == "12345678"
        assert profile["address"]["line1"] == "1 Test Street"
        assert profile["address"]["postcode"] == "ST16 1AA"
        assert profile["is_vat_registered"] is True
        assert profile["vat_registration_number"] == "GB123456789"


def test_vat_rate_label_does_not_drop_significant_zero(app):
    with app.app_context():
        organisation, _, _ = _setup()
        standard = TaxCode.query.filter_by(organisation_id=organisation.id, code="T20").one()
        line = type("Line", (), {"tax_code": standard})()
        assert _vat_rate_label(line) == "20%"


def test_vat_invoice_requires_supplier_and_customer_identity(app):
    with app.app_context():
        _, context, accounts = _setup()
        TaxService.update_profile(
            context,
            jurisdiction="GB",
            is_vat_registered=True,
            registration_number="GB123456789",
            scheme="standard",
            return_frequency="quarterly",
        )
        customer = SalesService.create_customer(context, name="Missing Address Customer")
        tax_code = TaxCode.query.filter_by(organisation_id=context.organisation_id, code="T20").one()
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="VAT-MISSING-001",
            invoice_date=date(2026, 9, 17),
            tax_point=date(2026, 9, 16),
            due_date=None,
            description="Taxable service",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            tax_code_id=tax_code.id,
        )

        with pytest.raises(ValueError, match="VAT invoice cannot be generated") as exc:
            FinancialDocumentPdfService.sales_invoice(context, invoice.id)
        message = str(exc.value)
        assert "supplier address" in message
        assert "customer address" in message


def test_complete_vat_invoice_generates_pdf_with_tax_point_override(app):
    with app.app_context():
        _, context, accounts = _setup()
        _complete_profile(context)
        customer = SalesService.create_customer(context, name="VAT Customer")
        customer.address = {
            "line1": "10 Customer Road",
            "city": "Birmingham",
            "postcode": "B1 1AA",
            "country": "United Kingdom",
        }
        db.session.commit()

        tax_code = TaxCode.query.filter_by(organisation_id=context.organisation_id, code="T20").one()
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="VAT-INV-001",
            invoice_date=date(2026, 9, 17),
            due_date=None,
            description="Taxable service",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            tax_code_id=tax_code.id,
            metadata={"issue_date": "2026-09-17"},
        )

        assert invoice.tax_point == date(2026, 9, 16)
        pdf, filename = FinancialDocumentPdfService.sales_invoice(context, invoice.id)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 3000
        assert filename == "invoice-VAT-INV-001.pdf"


def test_business_profile_page_is_registered(client, app):
    login = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert login.status_code == 200
    response = client.get("/business-profile/")
    assert response.status_code == 200
    assert b"Business Profile" in response.data or b"Business details" in response.data
