from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.quote_models import SalesQuote
from ledgerone.modules.sales.quotes import SalesQuoteService
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.tax.models import TaxCode
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService


def _context_and_accounts():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def test_quote_is_non_posting_until_conversion(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        customer = SalesService.create_customer(context, name="Quote Customer")
        before_journals = Journal.query.count()

        quote = SalesQuoteService.create_quote(
            context,
            customer_id=customer.id,
            quote_number="QUO-001",
            quote_date=date(2026, 9, 14),
            expiry_date=date(2026, 10, 14),
            description="Quoted service",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )

        assert quote.status == "draft"
        assert quote.total == Decimal("100.00")
        assert quote.converted_invoice_id is None
        assert Journal.query.count() == before_journals

        invoice, converted = SalesQuoteService.convert_to_invoice(
            context,
            quote.id,
            invoice_number="INV-FROM-QUOTE-001",
            invoice_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
        )

        assert converted.status == "converted"
        assert converted.converted_invoice_id == invoice.id
        assert invoice.status == "posted"
        assert invoice.total == Decimal("100.00")
        assert invoice.metadata_json["source_quote_id"] == quote.id
        assert invoice.metadata_json["source_quote_number"] == "QUO-001"
        assert Journal.query.count() == before_journals + 1

        with pytest.raises(ValueError, match="already been converted"):
            SalesQuoteService.convert_to_invoice(
                context,
                quote.id,
                invoice_number="INV-DUPLICATE",
                invoice_date=date(2026, 9, 16),
            )


def test_vat_quote_converts_through_standard_invoice_posting(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        SettingsService.set_module_enabled(context, "tax", True)
        tax_code = TaxCode.query.filter_by(
            organisation_id=context.organisation_id, code="T20"
        ).one()
        customer = SalesService.create_customer(context, name="VAT Quote Customer")

        quote = SalesQuoteService.create_quote(
            context,
            customer_id=customer.id,
            quote_number="QUO-VAT-001",
            quote_date=date(2026, 9, 14),
            expiry_date=None,
            description="VAT quoted service",
            amount="100.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
            tax_code_id=tax_code.id,
        )

        assert quote.subtotal == Decimal("100.00")
        assert quote.tax_total == Decimal("20.00")
        assert quote.total == Decimal("120.00")
        assert Journal.query.count() == 0

        invoice, _ = SalesQuoteService.convert_to_invoice(
            context,
            quote.id,
            invoice_number="INV-VAT-QUOTE-001",
            invoice_date=date(2026, 9, 15),
        )

        journal = db.session.get(Journal, invoice.posted_journal_id)
        by_account = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_account["1200"] == (Decimal("120.00"), Decimal("0.00"))
        assert by_account["4000"] == (Decimal("0.00"), Decimal("100.00"))
        assert by_account["2200"] == (Decimal("0.00"), Decimal("20.00"))


def test_locked_period_conversion_rolls_back_invoice_and_quote_state(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        customer = SalesService.create_customer(context, name="Locked Quote Customer")
        quote = SalesQuoteService.create_quote(
            context,
            customer_id=customer.id,
            quote_number="QUO-LOCKED-001",
            quote_date=date(2026, 9, 14),
            expiry_date=None,
            description="Locked conversion",
            amount="50.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        period = LedgerService.create_period(
            context,
            name="October 2026 quote lock",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        LedgerService.set_period_locked(context, period.id, locked=True)
        before_invoices = SalesInvoice.query.count()
        before_journals = Journal.query.count()

        with pytest.raises(LedgerError, match="locked period"):
            SalesQuoteService.convert_to_invoice(
                context,
                quote.id,
                invoice_number="INV-LOCKED-QUOTE",
                invoice_date=date(2026, 10, 5),
            )

        db.session.expire_all()
        persisted_quote = db.session.get(SalesQuote, quote.id)
        assert persisted_quote.status == "draft"
        assert persisted_quote.converted_invoice_id is None
        assert SalesInvoice.query.count() == before_invoices
        assert Journal.query.count() == before_journals


def test_rejected_and_unaccepted_expired_quotes_do_not_convert(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        customer = SalesService.create_customer(context, name="Expired Quote Customer")
        quote = SalesQuoteService.create_quote(
            context,
            customer_id=customer.id,
            quote_number="QUO-EXPIRED-001",
            quote_date=date(2026, 9, 1),
            expiry_date=date(2026, 9, 10),
            description="Expired quote",
            amount="25.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        with pytest.raises(ValueError, match="expired"):
            SalesQuoteService.convert_to_invoice(
                context,
                quote.id,
                invoice_number="INV-EXPIRED",
                invoice_date=date(2026, 9, 14),
            )

        SalesQuoteService.set_status(context, quote.id, status="accepted")
        invoice, _ = SalesQuoteService.convert_to_invoice(
            context,
            quote.id,
            invoice_number="INV-ACCEPTED-EXPIRED",
            invoice_date=date(2026, 9, 14),
        )
        assert invoice.status == "posted"
