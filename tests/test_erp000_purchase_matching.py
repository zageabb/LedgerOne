"""ERP-000 purchase invoice matching preview, permissions and discrepancies."""
from datetime import date

import pytest

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.purchase_matching import PurchaseMatchService
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 17)


def _po():
    org = Organisation.query.one()
    context = AccessContext.system(org.id)
    accounts = {a.code: a.id for a in Account.query.filter_by(organisation_id=org.id).all()}
    supplier = PurchasesService.create_supplier(context, name="Matching supplier")
    po = PurchaseOrderService.create_order(
        context, supplier_id=supplier.id, order_number="PO-MATCH-001",
        order_date=DAY, expected_date=None, description="Matching material",
        amount="100.00", payable_account_id=accounts["2100"],
        expense_account_id=accounts["5000"])
    PurchaseOrderService.set_status(context, po.id, status="approved")
    return context, po


def _preview(context, po, *, qty="1", price="100", mode="three_way", reference="INV-001"):
    return PurchaseMatchService.preview(
        context, order_id=po.id, supplier_invoice_reference=reference,
        match_type=mode, lines=[
            {"order_line_id": po.lines[0].id, "quantity": qty, "unit_price": price}])


def test_two_way_matches_unreceived_order_but_three_way_requires_grn(app):
    with app.app_context():
        context, po = _po()
        before = Journal.query.count()
        two_way = _preview(context, po, mode="two_way")
        assert two_way["matched"] is True
        assert two_way["posting_authorised"] is False
        three_way = _preview(context, po)
        assert "line_1:exceeds_received_quantity" in three_way["issues"]
        assert Journal.query.count() == before

        grn = CommercialDocumentService.create(
            context, document_type="grn", order_id=po.id,
            document_date=DAY, lines=[
                {"order_line_id": po.lines[0].id, "quantity": "1"}])
        assert grn.document_type == "grn"
        matched = _preview(context, po)
        assert matched["matched"] is True
        assert matched["lines"][0]["received_quantity"] == "1.0000"
        assert Journal.query.count() == before


def test_price_quantity_variance_and_tolerance(app):
    with app.app_context():
        context, po = _po()
        CommercialDocumentService.create(
            context, document_type="grn", order_id=po.id,
            document_date=DAY, lines=[
                {"order_line_id": po.lines[0].id, "quantity": "1"}])
        mismatch = _preview(context, po, qty="2", price="108")
        assert "line_1:exceeds_ordered_quantity" in mismatch["issues"]
        assert "line_1:exceeds_received_quantity" in mismatch["issues"]
        assert "line_1:unit_price_variance" in mismatch["issues"]
        allowed = PurchaseMatchService.preview(
            context, order_id=po.id, supplier_invoice_reference="INV-OK",
            lines=[{"order_line_id": po.lines[0].id,
                    "quantity": "1", "unit_price": "103"}],
            price_tolerance_percent="5")
        assert allowed["matched"] is True
        with pytest.raises(ValueError, match="between 0 and 100"):
            PurchaseMatchService.preview(
                context, order_id=po.id, supplier_invoice_reference="INV-BAD",
                lines=[{"order_line_id": po.lines[0].id,
                        "quantity": "1", "unit_price": "100"}],
                price_tolerance_percent="-1")


def test_rejects_cross_company_match_and_invalid_line(app):
    with app.app_context():
        context, po = _po()
        foreign = AccessContext.system("different-company")
        with pytest.raises(ValueError, match="Purchase order not found"):
            _preview(foreign, po)
        with pytest.raises(ValueError, match="uniquely identify"):
            PurchaseMatchService.preview(
                context, order_id=po.id,
                supplier_invoice_reference="INV-X",
                lines=[{"order_line_id": "not-a-po-line",
                        "quantity": "1", "unit_price": "100"}])


def test_duplicate_supplier_bill_reference_is_flagged(app):
    with app.app_context():
        context, po = _po()
        # A supplier bill can already exist independently of this order.
        PurchasesService.create_bill(
            context, supplier_id=po.supplier_id,
            bill_number="B-REF-100", supplier_invoice_reference="DUP-REF",
            bill_date=DAY, due_date=DAY,
            description="Existing invoice", amount="25",
            payable_account_id=po.payable_account_id,
            expense_account_id=po.lines[0].expense_account_id)
        preview = _preview(context, po, reference="DUP-REF", mode="two_way")
        assert "duplicate_supplier_invoice_reference" in preview["issues"]
        assert preview["matched"] is False


def test_prior_po_linked_bill_blocks_reuse_without_line_allocations(app):
    with app.app_context():
        context, po = _po()
        assert _preview(context, po, mode="two_way")["matched"] is True
        existing_bill = PurchasesService.create_bill(
            context, supplier_id=po.supplier_id,
            bill_number="B-PO-LINKED-001",
            supplier_invoice_reference="OLDER-SUPPLIER-INVOICE",
            bill_date=DAY, due_date=DAY,
            description="Previously invoiced PO material",
            amount="25",
            payable_account_id=po.payable_account_id,
            expense_account_id=po.lines[0].expense_account_id,
            metadata={"source_purchase_order_id": po.id},
        )
        result = _preview(context, po, reference="DIFFERENT-INVOICE", mode="two_way")
        assert result["matched"] is False
        assert "existing_po_bill_requires_line_allocation" in result["issues"]
        assert "duplicate_supplier_invoice_reference" not in result["issues"]
        assert result["existing_linked_bill_count"] == 1
        assert result["existing_linked_bill_ids"] == [existing_bill.id]
        assert result["posting_authorised"] is False


def test_bill_for_different_po_does_not_block_matching(app):
    with app.app_context():
        context, po = _po()
        PurchasesService.create_bill(
            context, supplier_id=po.supplier_id,
            bill_number="B-OTHER-PO-001",
            supplier_invoice_reference="OTHER-PO-INVOICE",
            bill_date=DAY, due_date=DAY,
            description="An unrelated purchase",
            amount="25",
            payable_account_id=po.payable_account_id,
            expense_account_id=po.lines[0].expense_account_id,
            metadata={"source_purchase_order_id": "unrelated-po"},
        )
        result = _preview(context, po, mode="two_way")
        assert result["matched"] is True
        assert result["existing_linked_bill_count"] == 0
        assert result["existing_linked_bill_ids"] == []
