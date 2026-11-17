"""ERP-000 multi-line sales/purchase order authoring tests."""
from datetime import date
from decimal import Decimal

import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 17)


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    account_ids = {a.code: a.id for a in Account.query.filter_by(
        organisation_id=organisation.id).all()}
    supplier = PurchasesService.create_supplier(context, name="Multi-line supplier")
    customer = SalesService.create_customer(context, name="Multi-line customer")
    return context, account_ids, supplier, customer


def test_purchase_order_stores_item_quantities_and_line_totals_without_posting(app):
    with app.app_context():
        context, accounts, supplier, customer = _setup()
        before = Journal.query.count()
        po = MultiLineOrderService.create(
            context, kind="purchase", party_id=supplier.id,
            order_number="PO-MULTI-001", order_date=DAY, expected_date=None,
            control_account_id=accounts["2100"],
            lines=[
                {"description": "Fasteners", "quantity": "5",
                 "unit_price": "12.34", "account_id": accounts["5000"]},
                {"description": "Bolts", "quantity": "2.5",
                 "unit_price": "8.00", "account_id": accounts["5000"]},
            ],
        )
        assert po.status == "draft"
        assert len(po.lines) == 2
        assert po.subtotal == Decimal("81.70")
        assert po.total == Decimal("81.70")
        assert po.lines[0].quantity == Decimal("5")
        assert po.lines[1].quantity == Decimal("2.5")
        assert Journal.query.count() == before


def test_sales_order_lines_enforce_company_accounts_and_currency(app):
    with app.app_context():
        context, accounts, supplier, customer = _setup()
        lines = [
            {"description": "Installation", "quantity": "2",
             "unit_price": "150", "account_id": accounts["4000"]},
            {"description": "Support", "quantity": "1",
             "unit_price": "75", "account_id": accounts["4000"]},
        ]
        so = MultiLineOrderService.create(
            context, kind="sales", party_id=customer.id,
            order_number="SO-MULTI-001", order_date=DAY, expected_date=None,
            control_account_id=accounts["1200"], lines=lines)
        assert so.subtotal == Decimal("375.00")
        assert len(so.lines) == 2
        with pytest.raises(ValueError, match="Invalid accounting account"):
            MultiLineOrderService.create(
                context, kind="sales", party_id=customer.id,
                order_number="SO-INVALID-ACCOUNT", order_date=DAY,
                expected_date=None, control_account_id=accounts["1200"],
                lines=[{**lines[0], "account_id": accounts["5000"]}])
        with pytest.raises(ValueError, match="Multi-currency"):
            MultiLineOrderService.create(
                context, kind="sales", party_id=customer.id,
                order_number="SO-USD", order_date=DAY, expected_date=None,
                control_account_id=accounts["1200"], lines=lines, currency="USD")
        with pytest.raises(ValueError, match="quantity must be positive"):
            MultiLineOrderService.create(
                context, kind="sales", party_id=customer.id,
                order_number="SO-NEG", order_date=DAY, expected_date=None,
                control_account_id=accounts["1200"],
                lines=[{**lines[0], "quantity": "-1"}])


def test_order_builder_rejects_cross_company_suppliers(app):
    with app.app_context():
        context, accounts, supplier, customer = _setup()
        foreign = AccessContext.system("not-the-company")
        with pytest.raises(ValueError, match="Company not found"):
            MultiLineOrderService.create(
                foreign, kind="purchase", party_id=supplier.id,
                order_number="PO-FOREIGN", order_date=DAY, expected_date=None,
                control_account_id=accounts["2100"],
                lines=[{"description": "Foreign order", "quantity": "1",
                        "unit_price": "10", "account_id": accounts["5000"]}])
