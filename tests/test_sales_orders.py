from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.order_models import SalesOrder
from ledgerone.modules.sales.orders import SalesOrderService
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


def _create_order(context, accounts, customer, number="SO-001", amount="100.00", tax_code_id=None):
    return SalesOrderService.create_order(
        context,
        customer_id=customer.id,
        order_number=number,
        order_date=date(2026, 9, 14),
        requested_delivery_date=date(2026, 9, 28),
        description="Ordered service",
        amount=amount,
        receivable_account_id=accounts["1200"],
        revenue_account_id=accounts["4000"],
        tax_code_id=tax_code_id,
    )


def test_sales_order_is_non_posting_and_requires_confirmation(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        customer = SalesService.create_customer(context, name="Order Customer")
        before_journals = Journal.query.count()
        order = _create_order(context, accounts, customer)

        assert order.status == "draft"
        assert order.total == Decimal("100.00")
        assert order.converted_invoice_id is None
        assert Journal.query.count() == before_journals

        with pytest.raises(ValueError, match="must be confirmed"):
            SalesOrderService.convert_to_invoice(
                context,
                order.id,
                invoice_number="INV-FROM-SO-001",
                invoice_date=date(2026, 9, 15),
            )
        assert Journal.query.count() == before_journals

        SalesOrderService.set_status(context, order.id, status="confirmed")
        assert Journal.query.count() == before_journals
        invoice, converted = SalesOrderService.convert_to_invoice(
            context,
            order.id,
            invoice_number="INV-FROM-SO-001",
            invoice_date=date(2026, 9, 15),
        )
        assert converted.status == "converted"
        assert converted.converted_invoice_id == invoice.id
        assert invoice.status == "posted"
        assert invoice.total == Decimal("100.00")
        assert invoice.metadata_json["source_sales_order_id"] == order.id
        assert invoice.metadata_json["source_sales_order_number"] == "SO-001"
        assert Journal.query.count() == before_journals + 1

        with pytest.raises(ValueError, match="already been converted"):
            SalesOrderService.convert_to_invoice(
                context,
                order.id,
                invoice_number="INV-DUPLICATE-SO",
                invoice_date=date(2026, 9, 16),
            )


def test_vat_sales_order_converts_through_standard_invoice_posting(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        SettingsService.set_module_enabled(context, "tax", True)
        tax_code = TaxCode.query.filter_by(
            organisation_id=context.organisation_id, code="T20"
        ).one()
        customer = SalesService.create_customer(context, name="VAT Order Customer")
        before_journals = Journal.query.count()
        order = _create_order(
            context,
            accounts,
            customer,
            number="SO-VAT-001",
            tax_code_id=tax_code.id,
        )
        assert order.subtotal == Decimal("100.00")
        assert order.tax_total == Decimal("20.00")
        assert order.total == Decimal("120.00")
        assert Journal.query.count() == before_journals

        SalesOrderService.set_status(context, order.id, status="confirmed")
        invoice, _ = SalesOrderService.convert_to_invoice(
            context,
            order.id,
            invoice_number="INV-VAT-SO-001",
            invoice_date=date(2026, 9, 15),
        )
        journal = db.session.get(Journal, invoice.posted_journal_id)
        by_account = {line.account.code: (line.debit, line.credit) for line in journal.lines}
        assert by_account["1200"] == (Decimal("120.00"), Decimal("0.00"))
        assert by_account["4000"] == (Decimal("0.00"), Decimal("100.00"))
        assert by_account["2200"] == (Decimal("0.00"), Decimal("20.00"))


def test_sales_order_conversion_inherits_customer_payment_terms(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        customer = SalesService.create_customer(
            context, name="Order Terms Customer", payment_terms_days=12
        )
        order = _create_order(context, accounts, customer, number="SO-TERMS-001")
        SalesOrderService.set_status(context, order.id, status="confirmed")
        invoice, _ = SalesOrderService.convert_to_invoice(
            context,
            order.id,
            invoice_number="INV-SO-TERMS",
            invoice_date=date(2026, 9, 20),
            due_date=None,
        )
        assert invoice.due_date == date(2026, 10, 2)


def test_cancelled_sales_order_cannot_convert(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        customer = SalesService.create_customer(context, name="Cancelled Order Customer")
        order = _create_order(context, accounts, customer, number="SO-CANCELLED-001")
        SalesOrderService.set_status(context, order.id, status="cancelled")
        with pytest.raises(ValueError, match="cancelled"):
            SalesOrderService.convert_to_invoice(
                context,
                order.id,
                invoice_number="INV-CANCELLED-SO",
                invoice_date=date(2026, 9, 15),
            )


def test_locked_period_conversion_rolls_back_invoice_and_order_state(app):
    with app.app_context():
        context, accounts = _context_and_accounts()
        customer = SalesService.create_customer(context, name="Locked Order Customer")
        order = _create_order(context, accounts, customer, number="SO-LOCKED-001", amount="50.00")
        SalesOrderService.set_status(context, order.id, status="confirmed")
        period = LedgerService.create_period(
            context,
            name="October 2026 sales order lock",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        LedgerService.set_period_locked(context, period.id, locked=True)
        before_invoices = SalesInvoice.query.count()
        before_journals = Journal.query.count()

        with pytest.raises(LedgerError, match="locked period"):
            SalesOrderService.convert_to_invoice(
                context,
                order.id,
                invoice_number="INV-LOCKED-SO",
                invoice_date=date(2026, 10, 5),
            )

        db.session.expire_all()
        persisted_order = db.session.get(SalesOrder, order.id)
        assert persisted_order.status == "confirmed"
        assert persisted_order.converted_invoice_id is None
        assert SalesInvoice.query.count() == before_invoices
        assert Journal.query.count() == before_journals
