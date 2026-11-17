"""ERP-000 explicit item accounting treatment (stock vs non-stock)."""
from datetime import date

import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext


def _context():
    org = Organisation.query.one()
    ctx = AccessContext.system(org.id)
    accounts = {a.code: a.id for a in Account.query.filter_by(organisation_id=org.id).all()}
    return ctx, accounts


def test_purchase_lines_store_stock_treatment_but_do_not_post(app):
    with app.app_context():
        ctx, a = _context()
        supplier = PurchasesService.create_supplier(ctx, name="Stock treatment supplier")
        before = Journal.query.count()
        order = MultiLineOrderService.create(
            ctx, kind="purchase", party_id=supplier.id, order_number="PO-STOCK-TREAT",
            order_date=date(2026, 11, 17), expected_date=None,
            control_account_id=a["2100"],
            lines=[
                {"description": "Goods", "quantity": "2", "unit_price": "30",
                 "account_id": a["5000"], "item_treatment": "stock"},
                {"description": "Installation", "quantity": "1", "unit_price": "20",
                 "account_id": a["5000"], "item_treatment": "expense"},
            ])
        assert [x.dimensions["item_treatment"] for x in order.lines] == ["stock", "expense"]
        assert Journal.query.count() == before


def test_sales_lines_default_to_service_and_reject_invalid_treatment(app):
    with app.app_context():
        ctx, a = _context()
        customer = SalesService.create_customer(ctx, name="Stock treatment customer")
        kwargs = dict(kind="sales", party_id=customer.id,
                      order_date=date(2026, 11, 17), expected_date=None,
                      control_account_id=a["1200"])
        order = MultiLineOrderService.create(
            ctx, order_number="SO-SERVICE-DEFAULT", **kwargs,
            lines=[{"description": "Consulting", "quantity": "1",
                    "unit_price": "50", "account_id": a["4000"]}])
        assert order.lines[0].dimensions["item_treatment"] == "service"
        with pytest.raises(ValueError, match="Invalid item accounting treatment"):
            MultiLineOrderService.create(
                ctx, order_number="SO-BAD-STOCK", **kwargs,
                lines=[{"description": "Invalid", "quantity": "1", "unit_price": "50",
                        "account_id": a["4000"], "item_treatment": "raw-material"}])
        with pytest.raises(ValueError, match="Invalid item accounting treatment"):
            MultiLineOrderService.create(
                ctx, order_number="SO-SPOOF", **kwargs,
                lines=[{"description": "Invalid", "quantity": "1", "unit_price": "50",
                        "account_id": a["4000"], "item_treatment": "invented",
                        "dimensions": {"item_treatment": "stock"}}])
