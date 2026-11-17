"""GRNI receipt-to-bill allocation preview preserves posted vs unposted distinction."""
from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, new_id
from ledgerone.models.ledger import Account
from ledgerone.services.inventory_accounting import InventoryAccountingConfiguration
from ledgerone.services.ledger import LedgerService
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.commercial.models import CommercialAccountingEvent, GRNIInvoiceAllocation
from ledgerone.modules.commercial.grni_reconciliation import GRNIReconciliationService
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 17)


def _make():
    org = Organisation.query.one()
    ctx = AccessContext.system(org.id)
    ids = {a.code: a.id for a in Account.query.filter_by(organisation_id=org.id)}
    supplier = PurchasesService.create_supplier(ctx, name="GRNI reconciliation supplier")
    order = MultiLineOrderService.create(
        ctx, kind="purchase", party_id=supplier.id, order_number="PO-GRNI-ALLOC",
        order_date=DAY, expected_date=None, control_account_id=ids["2100"],
        lines=[{"description": "Stock", "quantity": "4", "unit_price": "15",
                "account_id": ids["5000"], "item_treatment": "stock"}])
    PurchaseOrderService.set_status(ctx, order.id, status="approved")
    grn = CommercialDocumentService.create(
        ctx, document_type="grn", order_id=order.id, document_date=DAY,
        lines=[{"order_line_id": order.lines[0].id, "quantity": "3"}])
    return ctx, order, grn, ids


def test_unposted_grn_does_not_count_as_ledger_accrual(app):
    with app.app_context():
        ctx, order, grn, _ = _make()
        data = GRNIReconciliationService.preview(ctx, order_id=order.id)
        assert data["total_posted_grni"] == "0.00"
        assert data["outstanding_grni"] == "0.00"
        assert data["lines"][0]["accrual_posted"] is False
        assert "without a posted GRNI journal" in data["issues"][0]
        assert data["preview_only"]


def test_posted_grn_tracks_partially_allocated_quantities(app):
    with app.app_context():
        ctx, order, grn, ids = _make()
        grni = LedgerService.create_account(ctx, code="GRNI-ALLOC", name="GRNI", account_type="liability")
        stock = LedgerService.create_account(ctx, code="STOCK-ALLOC", name="Inventory", account_type="asset")
        cogs = LedgerService.create_account(ctx, code="COGS-ALLOC", name="COGS", account_type="expense")
        InventoryAccountingConfiguration.configure(ctx, grni_clearing=grni.id,
                                                   inventory_asset=stock.id, cost_of_goods_sold=cogs.id)
        journal = LedgerService.post_journal(
            ctx, journal_date=DAY, description="Test GRNI accrual",
            reference="GRNI-TEST", source_module="purchases",
            source_reference=grn.id,
            lines=[
                {"account_id": stock.id, "debit": "45", "credit": "0"},
                {"account_id": grni.id, "debit": "0", "credit": "45"},
            ])
        event = CommercialAccountingEvent(
            id=new_id(), organisation_id=ctx.organisation_id,
            document_id=grn.id, event_type="grn_inventory_accrual",
            journal_id=journal.id, posted_value=Decimal("45.00"),
            metadata_json={})
        db.session.add(event)
        db.session.commit()
        data = GRNIReconciliationService.preview(ctx, order_id=order.id)
        assert data["outstanding_grni"] == "45.00"
        assert data["lines"][0]["available_quantity"] == "3.0000"
        # Synthetic matched bill fixture: posting and allocation are future
        # functionality. Test read-side evidence validation without enabling
        # the production clearing pathway.
        clearing = LedgerService.post_journal(
            ctx, journal_date=DAY, description="Matched invoice GRNI clearing",
            reference="GRNI-BILL-TEST", source_module="purchases",
            source_reference="synthetic-clearing-test",
            lines=[
                {"account_id": grni.id, "debit": "15", "credit": "0"},
                {"account_id": ids["2100"], "debit": "0", "credit": "15"},
            ])
        bill = PurchaseBill(
            id=new_id(), organisation_id=ctx.organisation_id,
            supplier_id=order.supplier_id, bill_number="GRNI-ALLOC-BILL",
            bill_date=DAY, tax_point=DAY, due_date=DAY, status="posted",
            currency="GBP", subtotal=Decimal("15.00"),
            tax_total=Decimal("0.00"), total=Decimal("15.00"),
            posted_journal_id=clearing.id, metadata_json={})
        db.session.add(bill)
        db.session.flush()
        allocation = GRNIInvoiceAllocation(
            id=new_id(), organisation_id=ctx.organisation_id,
            bill_id=bill.id, clearing_journal_id=clearing.id,
            receipt_line_id=grn.lines[0].id,
            order_line_id=order.lines[0].id, quantity=Decimal("1"),
            accrual_value=Decimal("15.00"), invoice_net_value=Decimal("15.00"))
        db.session.add(allocation)
        db.session.commit()
        data = GRNIReconciliationService.preview(ctx, order_id=order.id)
        assert data["total_cleared_grni"] == "15.00"
        assert data["outstanding_grni"] == "30.00"
        assert data["lines"][0]["available_quantity"] == "2.0000"
        bill.posted_journal_id = journal.id
        db.session.commit()
        invalid = GRNIReconciliationService.preview(ctx, order_id=order.id)
        assert invalid["total_cleared_grni"] == "0.00"
        assert invalid["outstanding_grni"] == "45.00"
        assert any("does not have verified GRNI" in issue for issue in invalid["issues"])
        # A reversal removes the receipt accrual from the reconciliation.
        LedgerService.reverse_journal(ctx, journal.id, reversal_date=DAY,
                                      reason="Testing return/reversal accounting")
        reversed_report = GRNIReconciliationService.preview(ctx, order_id=order.id)
        assert reversed_report["total_posted_grni"] == "0.00"
        assert reversed_report["outstanding_grni"] == "0.00"


def test_reconciliation_is_company_scoped(app):
    with app.app_context():
        ctx, order, grn, ids = _make()
        foreign = AccessContext.system("foreign-company")
        with pytest.raises(ValueError, match="Purchase order not found"):
            GRNIReconciliationService.preview(foreign, order_id=order.id)
