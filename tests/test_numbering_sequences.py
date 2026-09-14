from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import NumberSequence, Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.orders import SalesOrderService
from ledgerone.modules.sales.quotes import SalesQuoteService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService
from ledgerone.services.numbering import NumberSequenceService


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def test_defaults_and_configuration(app):
    with app.app_context():
        context, _ = _setup()
        rows = NumberSequenceService.list_sequences(context.organisation_id)
        assert len(rows) == 8
        assert NumberSequenceService.peek(context.organisation_id, "sales_invoice") == "INV-0001"
        updated = NumberSequenceService.update(
            context,
            "sales_invoice",
            prefix="SI-",
            suffix="-GB",
            next_value=27,
            padding=6,
        )
        assert NumberSequenceService.format_number(updated) == "SI-000027-GB"


def test_auto_invoice_and_bill_numbers_increment_and_explicit_numbers_do_not(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Numbered Customer")
        supplier = PurchasesService.create_supplier(context, name="Numbered Supplier")

        invoice1 = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="First numbered invoice",
            amount="10.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        explicit = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="CUSTOM-99",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Explicit invoice",
            amount="10.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        invoice2 = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Second numbered invoice",
            amount="10.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        bill1 = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="",
            bill_date=date(2026, 9, 14),
            due_date=None,
            description="First numbered bill",
            amount="10.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
        )

        assert invoice1.invoice_number == "INV-0001"
        assert explicit.invoice_number == "CUSTOM-99"
        assert invoice2.invoice_number == "INV-0002"
        assert bill1.bill_number == "BILL-0001"
        assert NumberSequenceService.peek(context.organisation_id, "sales_invoice") == "INV-0003"


def test_quote_and_sales_order_have_independent_sequences(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Commercial Customer")
        quote = SalesQuoteService.create_quote(
            context,
            customer_id=customer.id,
            quote_number="",
            quote_date=date(2026, 9, 14),
            expiry_date=None,
            description="Quote",
            amount="25.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        order = SalesOrderService.create_order(
            context,
            customer_id=customer.id,
            order_number="",
            order_date=date(2026, 9, 14),
            requested_delivery_date=None,
            description="Order",
            amount="25.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        assert quote.quote_number == "QUO-0001"
        assert order.order_number == "SO-0001"


def test_failed_auto_numbered_conversion_rolls_sequence_back(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Rollback Customer")
        order = SalesOrderService.create_order(
            context,
            customer_id=customer.id,
            order_number="SO-LOCK-1",
            order_date=date(2026, 9, 14),
            requested_delivery_date=None,
            description="Locked conversion",
            amount="50.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        SalesOrderService.set_status(context, order.id, status="confirmed")
        period = LedgerService.create_period(
            context,
            name="October lock for numbering",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        LedgerService.set_period_locked(context, period.id, locked=True)
        before = NumberSequenceService.peek(context.organisation_id, "sales_invoice")

        with pytest.raises(LedgerError, match="locked period"):
            SalesOrderService.convert_to_invoice(
                context,
                order.id,
                invoice_number="",
                invoice_date=date(2026, 10, 5),
                due_date=None,
            )

        db.session.expire_all()
        assert NumberSequenceService.peek(context.organisation_id, "sales_invoice") == before
        persisted = db.session.get(NumberSequence, NumberSequence.query.filter_by(
            organisation_id=context.organisation_id, sequence_key="sales_invoice"
        ).one().id)
        assert persisted.next_value == 1


def test_numbering_validation(app):
    with app.app_context():
        context, _ = _setup()
        with pytest.raises(ValueError, match="at least 1"):
            NumberSequenceService.update(context, "sales_invoice", prefix="INV-", next_value=0, padding=4)
        with pytest.raises(ValueError, match="between 1 and 12"):
            NumberSequenceService.update(context, "sales_invoice", prefix="INV-", next_value=1, padding=13)
        with pytest.raises(ValueError, match="Unknown"):
            NumberSequenceService.update(context, "made_up", prefix="X-", next_value=1, padding=4)
