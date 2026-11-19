"""PO-linked multi-line bill drafts preserve invoice quantities without journals."""
from datetime import date

import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.bill_drafts import PurchaseBillDraftService
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 19)


def _po():
    org = Organisation.query.one()
    ctx = AccessContext.system(org.id)
    accounts = {a.code: a.id for a in Account.query.filter_by(
        organisation_id=org.id).all()}
    supplier = PurchasesService.create_supplier(
        ctx, name="Multi-line draft supplier")
    po = MultiLineOrderService.create(
        ctx, kind="purchase", party_id=supplier.id,
        order_number="PO-BILL-DRAFT-001", order_date=DAY,
        expected_date=None, control_account_id=accounts["2100"],
        lines=[
            {"description": "Parts", "quantity": "5", "unit_price": "12",
             "account_id": accounts["5000"], "item_treatment": "stock"},
            {"description": "Handling", "quantity": "3", "unit_price": "7",
             "account_id": accounts["5000"], "item_treatment": "expense"},
        ])
    PurchaseOrderService.set_status(ctx, po.id, status="approved")
    return ctx, po


def _lines(po, *, qty1="2", qty2="1"):
    return [
        {"order_line_id": po.lines[0].id, "quantity": qty1, "unit_price": "12"},
        {"order_line_id": po.lines[1].id, "quantity": qty2, "unit_price": "7"},
    ]


def test_multiline_po_drafts_preserve_quantity_tax_and_no_journal(app):
    with app.app_context():
        ctx, po = _po()
        before = Journal.query.count()
        one = PurchaseBillDraftService.create(
            ctx, order_id=po.id, supplier_invoice_reference="SUP-001",
            bill_number="B-PO-DRAFT-01", bill_date=DAY, lines=_lines(po))
        assert one.status == "draft"
        assert one.posted_journal_id is None
        assert one.subtotal == 31
        assert one.total == one.subtotal + one.tax_total
        assert len(one.lines) == 2
        assert [line.quantity for line in one.lines] == [2, 1]
        assert [(line.dimensions or {}).get("source_purchase_order_line_id")
                for line in one.lines] == [po.lines[0].id, po.lines[1].id]
        two = PurchaseBillDraftService.create(
            ctx, order_id=po.id, supplier_invoice_reference="SUP-002",
            bill_number="B-PO-DRAFT-02", bill_date=DAY,
            lines=_lines(po, qty1="3", qty2="2"))
        assert len(two.lines) == 2
        assert Journal.query.count() == before
        assert PurchaseBill.query.count() == 2
        assert po.status == "approved"


def test_draft_rejects_overbilling_duplicate_supplier_reference_and_other_po(app):
    with app.app_context():
        ctx, po = _po()
        PurchaseBillDraftService.create(
            ctx, order_id=po.id, supplier_invoice_reference="SUP-001",
            bill_number="B-PO-DRAFT-01", bill_date=DAY, lines=_lines(po))
        with pytest.raises(ValueError, match="remaining PO quantity"):
            PurchaseBillDraftService.create(
                ctx, order_id=po.id, supplier_invoice_reference="SUP-002",
                bill_number="B-PO-DRAFT-02", bill_date=DAY,
                lines=_lines(po, qty1="4"))
        with pytest.raises(ValueError, match="reference already exists"):
            PurchaseBillDraftService.create(
                ctx, order_id=po.id, supplier_invoice_reference="SUP-001",
                bill_number="B-PO-DRAFT-03", bill_date=DAY, lines=_lines(po))
        with pytest.raises(ValueError, match="uniquely identify"):
            PurchaseBillDraftService.create(
                ctx, order_id=po.id, supplier_invoice_reference="SUP-004",
                bill_number="B-PO-DRAFT-04", bill_date=DAY,
                lines=[_lines(po)[0], _lines(po)[0]])
        with pytest.raises(ValueError, match="Purchase order not found"):
            PurchaseBillDraftService.create(
                AccessContext.system("other-org"),
                order_id=po.id, supplier_invoice_reference="SUP-005",
                bill_number="B-PO-DRAFT-05", bill_date=DAY, lines=_lines(po))


def test_draft_api_registration(app):
    with app.app_context():
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        assert "commercial_api.create_po_bill_draft" in endpoints


def test_dedicated_draft_browser_route_and_template_registered(app):
    with app.app_context():
        endpoints = {route.endpoint for route in app.url_map.iter_rules()}
        assert "purchase_orders.new_bill_draft" in endpoints
        assert app.jinja_env.get_template("commercial/bill_draft_editor.html")
        order_template = app.jinja_env.get_template("commercial/order_detail.html")
        assert order_template is not None
