"""GRN inventory accrual preview: stock/non-stock, accounts, cross-company, no posting."""
from datetime import date
from decimal import Decimal

import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.grn_accounting import GRNAccountingPreviewService
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext
from ledgerone.services.inventory_accounting import InventoryAccountingConfiguration
from ledgerone.services.ledger import LedgerService

DAY = date(2026, 11, 17)


def _setup():
    company = Organisation.query.one()
    ctx = AccessContext.system(company.id)
    a = {x.code: x.id for x in Account.query.filter_by(organisation_id=company.id).all()}
    supplier = PurchasesService.create_supplier(ctx, name="GRN accrual preview supplier")
    order = MultiLineOrderService.create(
        ctx, kind="purchase", party_id=supplier.id, order_number="PO-GRNI-PREVIEW",
        order_date=DAY, expected_date=None, control_account_id=a["2100"],
        lines=[
            {"description": "Stock item", "quantity": "5", "unit_price": "12.50",
             "account_id": a["5000"], "item_treatment": "stock"},
            {"description": "Non-stock service", "quantity": "2", "unit_price": "10",
             "account_id": a["5000"], "item_treatment": "expense"},
        ])
    PurchaseOrderService.set_status(ctx, order.id, status="approved")
    receipt = CommercialDocumentService.create(
        ctx, document_type="grn", order_id=order.id, document_date=DAY,
        lines=[
            {"order_line_id": order.lines[0].id, "quantity": "2"},
            {"order_line_id": order.lines[1].id, "quantity": "1"},
        ])
    return ctx, order, receipt


def test_grn_preview_requires_accounts_and_never_posts(app):
    with app.app_context():
        ctx, order, receipt = _setup()
        before = Journal.query.count()
        missing = GRNAccountingPreviewService.preview(ctx, grn_id=receipt.id)
        assert missing["posted"] is False
        assert missing["preview_only"] is True
        assert missing["issues"]
        grni = LedgerService.create_account(ctx, code="GRNI-PREV", name="GRNI", account_type="liability")
        stock = LedgerService.create_account(ctx, code="STOCK-PREV", name="Stock", account_type="asset")
        cogs = LedgerService.create_account(ctx, code="COGS-PREV", name="COGS", account_type="expense")
        InventoryAccountingConfiguration.configure(
            ctx, grni_clearing=grni.id, inventory_asset=stock.id,
            cost_of_goods_sold=cogs.id)
        result = GRNAccountingPreviewService.preview(ctx, grn_id=receipt.id)
        assert result["stock_cost_value"] == "25.00"
        assert result["issues"] == []
        assert result["lines"][0]["account_id"] == stock.id
        assert result["lines"][0]["debit"] == "25.00"
        assert result["lines"][1]["account_id"] == grni.id
        assert result["lines"][1]["credit"] == "25.00"
        assert result["posting_enabled"] is False
        assert Journal.query.count() == before


def test_grn_preview_rejects_other_company_and_wrong_document(app):
    with app.app_context():
        ctx, order, receipt = _setup()
        other = AccessContext.system("other-company")
        with pytest.raises(ValueError, match="GRN not found"):
            GRNAccountingPreviewService.preview(other, grn_id=receipt.id)
        with pytest.raises(ValueError, match="GRN not found"):
            GRNAccountingPreviewService.preview(ctx, grn_id="unknown")


def test_accounting_preview_screen_and_api_routes(app):
    with app.app_context():
        endpoints = {route.endpoint for route in app.url_map.iter_rules()}
        assert "purchase_orders.grn_accounting_preview" in endpoints
        assert "commercial_api.grn_accounting_preview" in endpoints
        assert app.jinja_env.get_template("commercial/grn_accounting_preview.html")
