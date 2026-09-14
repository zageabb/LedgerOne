from datetime import date

import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.quotes import SalesQuoteService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.payment_terms import PaymentTermsService


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def test_default_payment_terms_apply_when_due_date_is_omitted(app):
    with app.app_context():
        context, accounts = _setup()
        assert PaymentTermsService.get(context.organisation_id) == {
            "customer_days": 30,
            "supplier_days": 30,
        }
        customer = SalesService.create_customer(context, name="Default Terms Customer")
        supplier = PurchasesService.create_supplier(context, name="Default Terms Supplier")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-TERMS-DEFAULT",
            invoice_date=date(2026, 9, 1),
            due_date=None,
            description="Default terms sale",
            amount="10.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="BILL-TERMS-DEFAULT",
            bill_date=date(2026, 9, 1),
            due_date=None,
            description="Default terms purchase",
            amount="10.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
        )
        assert invoice.due_date == date(2026, 10, 1)
        assert bill.due_date == date(2026, 10, 1)


def test_contact_override_beats_organisation_default_and_explicit_date_beats_override(app):
    with app.app_context():
        context, accounts = _setup()
        PaymentTermsService.update(context, customer_days=45, supplier_days=60)
        customer = SalesService.create_customer(
            context, name="Seven Day Customer", payment_terms_days=7
        )
        supplier = PurchasesService.create_supplier(
            context, name="Fourteen Day Supplier", payment_terms_days=14
        )
        automatic_invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-TERMS-7",
            invoice_date=date(2026, 9, 1),
            due_date=None,
            description="Override sale",
            amount="10.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        automatic_bill = PurchasesService.create_bill(
            context,
            supplier_id=supplier.id,
            bill_number="BILL-TERMS-14",
            bill_date=date(2026, 9, 1),
            due_date=None,
            description="Override purchase",
            amount="10.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
        )
        explicit_invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-TERMS-EXPLICIT",
            invoice_date=date(2026, 9, 1),
            due_date=date(2026, 9, 20),
            description="Explicit due date",
            amount="10.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        assert automatic_invoice.due_date == date(2026, 9, 8)
        assert automatic_bill.due_date == date(2026, 9, 15)
        assert explicit_invoice.due_date == date(2026, 9, 20)


def test_quote_and_purchase_order_conversion_inherit_contact_terms(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(
            context, name="Quote Terms Customer", payment_terms_days=10
        )
        quote = SalesQuoteService.create_quote(
            context,
            customer_id=customer.id,
            quote_number="Q-TERMS-001",
            quote_date=date(2026, 9, 1),
            expiry_date=None,
            description="Quoted work",
            amount="25.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        invoice, _ = SalesQuoteService.convert_to_invoice(
            context,
            quote.id,
            invoice_number="INV-FROM-Q-TERMS",
            invoice_date=date(2026, 9, 5),
            due_date=None,
        )
        assert invoice.due_date == date(2026, 9, 15)

        supplier = PurchasesService.create_supplier(
            context, name="PO Terms Supplier", payment_terms_days=21
        )
        order = PurchaseOrderService.create_order(
            context,
            supplier_id=supplier.id,
            order_number="PO-TERMS-001",
            order_date=date(2026, 9, 1),
            expected_date=None,
            description="Ordered work",
            amount="30.00",
            payable_account_id=accounts["2100"],
            expense_account_id=accounts["5000"],
        )
        PurchaseOrderService.set_status(context, order.id, status="approved")
        bill, _ = PurchaseOrderService.convert_to_bill(
            context,
            order.id,
            bill_number="BILL-FROM-PO-TERMS",
            bill_date=date(2026, 9, 5),
            due_date=None,
        )
        assert bill.due_date == date(2026, 9, 26)


def test_zero_day_terms_and_validation_bounds(app):
    with app.app_context():
        context, accounts = _setup()
        PaymentTermsService.update(context, customer_days=0, supplier_days=0)
        customer = SalesService.create_customer(context, name="Immediate Customer")
        invoice = SalesService.create_invoice(
            context,
            customer_id=customer.id,
            invoice_number="INV-DUE-NOW",
            invoice_date=date(2026, 9, 14),
            due_date=None,
            description="Due now",
            amount="5.00",
            receivable_account_id=accounts["1200"],
            revenue_account_id=accounts["4000"],
        )
        assert invoice.due_date == date(2026, 9, 14)
        with pytest.raises(ValueError, match="between 0 and 365"):
            PaymentTermsService.update(context, customer_days=366, supplier_days=30)
        with pytest.raises(ValueError, match="between 0 and 365"):
            SalesService.create_customer(
                context, name="Invalid Terms Customer", payment_terms_days=-1
            )


def test_explicit_due_date_cannot_precede_document_date(app):
    with app.app_context():
        context, accounts = _setup()
        customer = SalesService.create_customer(context, name="Date Guard Customer")
        with pytest.raises(ValueError, match="cannot be before"):
            SalesService.create_invoice(
                context,
                customer_id=customer.id,
                invoice_number="INV-BAD-DUE",
                invoice_date=date(2026, 9, 14),
                due_date=date(2026, 9, 13),
                description="Bad due date",
                amount="5.00",
                receivable_account_id=accounts["1200"],
                revenue_account_id=accounts["4000"],
            )
