"""ERP-000 GRN journal linkage, no public activation, transaction and retry guards."""
from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, Setting
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.models import CommercialAccountingEvent
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.commercial.grn_posting import GRNPostingService
from ledgerone.modules.commercial.grn_accounting import GRNAccountingPreviewService
from ledgerone.modules.commercial.purchase_matching import PurchaseMatchService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext
from ledgerone.services.inventory_accounting import InventoryAccountingConfiguration
from ledgerone.services.ledger import LedgerService

DAY = date(2026, 11, 17)


def _configured_receipt():
    org = Organisation.query.one()
    ctx = AccessContext.system(org.id)
    accounts = {x.code: x.id for x in Account.query.filter_by(
        organisation_id=org.id).all()}
    supplier = PurchasesService.create_supplier(ctx, name="Safe stock receipt supplier")
    order = MultiLineOrderService.create(
        ctx, kind="purchase", party_id=supplier.id, order_number="PO-SAFE-ACCRUAL",
        order_date=DAY, expected_date=None, control_account_id=accounts["2100"],
        lines=[{"description": "Stock", "quantity": "3",
                "unit_price": "11", "account_id": accounts["5000"],
                "item_treatment": "stock"}])
    PurchaseOrderService.set_status(ctx, order.id, status="approved")
    receipt = CommercialDocumentService.create(
        ctx, document_type="grn", order_id=order.id,
        document_date=DAY, lines=[
            {"order_line_id": order.lines[0].id, "quantity": "2"}])
    grni = LedgerService.create_account(ctx, code="GRNI-POST", name="GRNI", account_type="liability")
    stock = LedgerService.create_account(ctx, code="STOCK-POST", name="Stock", account_type="asset")
    cogs = LedgerService.create_account(ctx, code="COGS-POST", name="COGS", account_type="expense")
    InventoryAccountingConfiguration.configure(
        ctx, grni_clearing=grni.id, inventory_asset=stock.id,
        cost_of_goods_sold=cogs.id)
    return ctx, receipt, grni, stock


def test_receipt_posting_is_disabled_in_user_settings(app):
    with app.app_context():
        ctx, receipt, grni, stock = _configured_receipt()
        before = Journal.query.count()
        preview = GRNAccountingPreviewService.preview(ctx, grn_id=receipt.id)
        assert preview["posted"] is False
        assert preview["journal_id"] is None
        assert preview["accounting_event_id"] is None
        with pytest.raises(ValueError, match="disabled until supplier invoice GRNI clearing"):
            GRNPostingService.post(ctx, grn_id=receipt.id)
        assert Journal.query.count() == before
        assert CommercialAccountingEvent.query.count() == 0


def test_atomic_posting_link_and_retry_protection_when_internally_certified(app):
    """Exercise posting only with an explicit internal test configuration."""
    with app.app_context():
        ctx, receipt, grni, stock = _configured_receipt()
        settings = Setting.query.filter_by(
            organisation_id=ctx.organisation_id,
            scope=InventoryAccountingConfiguration.SCOPE,
            key=InventoryAccountingConfiguration.KEY).one()
        value = dict(settings.value)
        value["receipt_posting_enabled"] = True
        value["grni_bill_clearing_certified"] = True
        settings.value = value
        db.session.commit()
        match_args = dict(
            order_id=receipt.order_id, supplier_invoice_reference="GRNI-COVER-001",
            lines=[{"order_line_id": receipt.lines[0].order_line_id,
                    "quantity": "2", "unit_price": "11"}],
        )
        unposted_match = PurchaseMatchService.preview(ctx, **match_args)
        assert unposted_match["matched"] is True
        assert unposted_match["grni_accrual_coverage_sufficient"] is False
        assert "line_1:grni_receipt_accrual_missing" in unposted_match["grni_issues"]
        assert unposted_match["lines"][0]["grni"]["posted_receipt_quantity"] == "0"
        before = Journal.query.count()
        event = GRNPostingService.post(ctx, grn_id=receipt.id)
        assert event.posted_value == Decimal("22.00")
        assert Journal.query.count() == before + 1
        assert event.journal.source_reference == receipt.id
        assert event.journal.total_debit == Decimal("22.00")
        assert event.journal.total_credit == Decimal("22.00")
        assert {line.account_id for line in event.journal.lines} == {grni.id, stock.id}
        assert GRNPostingService.linked_event(ctx, receipt.id).id == event.id
        preview = GRNAccountingPreviewService.preview(ctx, grn_id=receipt.id)
        assert preview["posted"] is True
        assert preview["preview_only"] is True
        assert preview["posting_enabled"] is False
        assert preview["journal_id"] == event.journal_id
        assert preview["accounting_event_id"] == event.id
        assert preview["posted_value"] == "22.00"
        assert preview["stock_cost_value"] == "22.00"
        assert preview["posted_total_debit"] == "22.00"
        assert preview["posted_total_credit"] == "22.00"
        assert len(preview["posted_journal_lines"]) == 2
        assert {row["account_id"] for row in preview["posted_journal_lines"]} == {grni.id, stock.id}
        assert preview["posted_breakdown"] == event.metadata_json["stock_lines"]
        # The recorded journal must remain visible even if Settings later
        # switch to another valid set of accounts.
        replacement_grni = LedgerService.create_account(
            ctx, code="GRNI-NEW", name="New GRNI", account_type="liability")
        replacement_stock = LedgerService.create_account(
            ctx, code="STOCK-NEW", name="New stock", account_type="asset")
        replacement_cogs = LedgerService.create_account(
            ctx, code="COGS-NEW", name="New COGS", account_type="expense")
        InventoryAccountingConfiguration.configure(
            ctx, grni_clearing=replacement_grni.id,
            inventory_asset=replacement_stock.id,
            cost_of_goods_sold=replacement_cogs.id)
        changed = GRNAccountingPreviewService.preview(ctx, grn_id=receipt.id)
        assert {row["account_id"] for row in changed["lines"]} == {
            replacement_grni.id, replacement_stock.id}
        assert {row["account_id"] for row in changed["posted_journal_lines"]} == {
            grni.id, stock.id}
        assert changed["posted_value"] == "22.00"
        assert changed["posted_breakdown"] == event.metadata_json["stock_lines"]
        assert app.jinja_env.get_template("commercial/grn_accounting_preview.html")
        linked_match = PurchaseMatchService.preview(ctx, **match_args)
        assert linked_match["matched"] is True
        assert linked_match["grni_accrual_coverage_sufficient"] is True
        assert linked_match["grni_clearing_posting_authorised"] is False
        assert linked_match["grni_issues"] == []
        assert linked_match["lines"][0]["grni"]["posted_receipt_quantity"] == "2.0000"
        assert linked_match["lines"][0]["grni"]["posted_receipt_cost"] == "22.00"
        with pytest.raises(ValueError, match="already linked"):
            GRNPostingService.post(ctx, grn_id=receipt.id)
        assert Journal.query.count() == before + 1


def test_rejects_cross_company_and_missing_grn(app):
    with app.app_context():
        ctx, receipt, grni, stock = _configured_receipt()
        other = AccessContext.system("other-org")
        with pytest.raises(ValueError, match="GRN not found"):
            GRNPostingService.linked_event(other, receipt.id)
        with pytest.raises(ValueError, match="GRN not found"):
            GRNPostingService.linked_event(ctx, "missing")
