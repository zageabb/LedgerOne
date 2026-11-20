"""Non-posting receipt/bill allocation validation and legacy bill safeguards."""
from datetime import date

import pytest

from ledgerone.models.core import Organisation
from ledgerone.extensions import db
from ledgerone.modules.commercial.models import PurchaseReceiptBillAllocation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.allocation_validation import PurchaseReceiptAllocationValidation
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 17)


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {a.code: a.id for a in Account.query.filter_by(
        organisation_id=organisation.id).all()}
    supplier = PurchasesService.create_supplier(context, name="Bill allocation validator")
    order = PurchaseOrderService.create_order(
        context, supplier_id=supplier.id, order_number="PO-ALLOC-VALID",
        order_date=DAY, expected_date=None, description="Material",
        amount="100", payable_account_id=accounts["2100"],
        expense_account_id=accounts["5000"])
    PurchaseOrderService.set_status(context, order.id, status="approved")
    receipt = CommercialDocumentService.create(
        context, document_type="grn", order_id=order.id,
        document_date=DAY, lines=[
            {"order_line_id": order.lines[0].id, "quantity": "1"}])
    bill, _ = PurchaseOrderService.convert_to_bill(
        context, order.id, bill_number="B-ALLOC-VALID", bill_date=DAY,
        supplier_invoice_reference="SUP-ALLOC-001")
    return context, order, receipt, bill


def test_legacy_bill_requires_verified_line_link_and_does_not_write(app):
    with app.app_context():
        context, order, receipt, bill = _setup()
        before = Journal.query.count()
        result = PurchaseReceiptAllocationValidation.preview(
            context, order_id=order.id, bill_id=bill.id,
            allocations=[{
                "receipt_line_id": receipt.lines[0].id,
                "bill_line_id": bill.lines[0].id,
                "quantity": "1",
            }])
        assert result["valid"] is False
        assert result["preview_only"] is True
        assert result["posting_authorised"] is False
        assert "allocation_1:bill_line_po_line_link_unverified" in result["issues"]
        assert Journal.query.count() == before


def test_quantity_limits_and_duplicate_pairs(app):
    with app.app_context():
        context, order, receipt, bill = _setup()
        proposal = {
            "receipt_line_id": receipt.lines[0].id,
            "bill_line_id": bill.lines[0].id,
            "quantity": "0.75",
        }
        result = PurchaseReceiptAllocationValidation.preview(
            context, order_id=order.id, bill_id=bill.id,
            allocations=[proposal, proposal])
        assert "allocation_2:duplicate_bill_receipt_line_pair" in result["issues"]
        assert "allocation_2:receipt_quantity_exceeded" in result["issues"]
        assert "allocation_2:bill_line_quantity_exceeded" in result["issues"]
        with pytest.raises(ValueError, match="up to four decimals"):
            PurchaseReceiptAllocationValidation.preview(
                context, order_id=order.id, bill_id=bill.id,
                allocations=[{**proposal, "quantity": "0.12345"}])


def test_rejects_cross_company_and_unknown_bill_line(app):
    with app.app_context():
        context, order, receipt, bill = _setup()
        proposal = [{
            "receipt_line_id": receipt.lines[0].id,
            "bill_line_id": "not-a-bill-line", "quantity": "1",
        }]
        with pytest.raises(ValueError, match="Allocation line"):
            PurchaseReceiptAllocationValidation.preview(
                context, order_id=order.id, bill_id=bill.id, allocations=proposal)
        with pytest.raises(ValueError, match="Purchase order not found"):
            PurchaseReceiptAllocationValidation.preview(
                AccessContext.system("another-company"),
                order_id=order.id, bill_id=bill.id, allocations=proposal)


def test_preflight_rejects_invalid_prior_bill_lineage_and_keeps_journals_unchanged(app):
    with app.app_context():
        context, order, receipt, bill = _setup()
        baseline = Journal.query.count()
        corrupt = PurchaseReceiptBillAllocation(
            organisation_id=context.organisation_id,
            purchase_order_line_id=order.lines[0].id,
            receipt_line_id=receipt.lines[0].id,
            bill_line_id=bill.lines[0].id,
            quantity="0.25", receipt_cost="25", invoice_net="25",
        )
        db.session.add(corrupt)
        db.session.commit()
        result = PurchaseReceiptAllocationValidation.preview(
            context, order_id=order.id, bill_id=bill.id,
            allocations=[{
                "receipt_line_id": receipt.lines[0].id,
                "bill_line_id": bill.lines[0].id,
                "quantity": "0.25",
            }])
        assert result["valid"] is False
        assert "invalid_persisted_allocation_lineage" in result["issues"]
        assert corrupt.id in result["invalid_persisted_allocation_ids"]
        assert result["posting_authorised"] is False
        assert Journal.query.count() == baseline


def test_preflight_rejects_existing_receipt_overallocation(app):
    with app.app_context():
        context, order, receipt, bill = _setup()
        # Simulate a historical imported allocation with explicit PO line
        # provenance, but more allocated than was physically received.
        from sqlalchemy.orm.attributes import flag_modified
        bill_line = bill.lines[0]
        bill_line.dimensions = {
            **(bill_line.dimensions or {}),
            "source_purchase_order_line_id": order.lines[0].id,
        }
        flag_modified(bill_line, "dimensions")
        db.session.add(PurchaseReceiptBillAllocation(
            organisation_id=context.organisation_id,
            purchase_order_line_id=order.lines[0].id,
            receipt_line_id=receipt.lines[0].id,
            bill_line_id=bill_line.id,
            quantity="1.5", receipt_cost="150", invoice_net="150",
        ))
        db.session.commit()
        baseline = Journal.query.count()
        result = PurchaseReceiptAllocationValidation.preview(
            context, order_id=order.id, bill_id=bill.id,
            allocations=[{
                "receipt_line_id": receipt.lines[0].id,
                "bill_line_id": bill_line.id,
                "quantity": "0.25",
            }])
        assert result["valid"] is False
        assert "previous_receipt_overallocated" in result["issues"]
        assert "previous_bill_line_overallocated" in result["issues"]
        assert "allocation_1:duplicate_bill_receipt_line_pair" in result["issues"]
        assert Journal.query.count() == baseline


def test_allocation_preflight_api_route_is_read_only(app):
    with app.app_context():
        routes = {route.endpoint for route in app.url_map.iter_rules()}
        assert "commercial_api.validate_receipt_bill_allocations" in routes
        context, order, receipt, bill = _setup()
        baseline = Journal.query.count()
        preview = PurchaseReceiptAllocationValidation.preview(
            context, order_id=order.id, bill_id=bill.id,
            allocations=[{
                "receipt_line_id": receipt.lines[0].id,
                "bill_line_id": bill.lines[0].id, "quantity": "0.5",
            }])
        assert preview["posting_authorised"] is False
        assert preview["preview_only"] is True
        assert Journal.query.count() == baseline
