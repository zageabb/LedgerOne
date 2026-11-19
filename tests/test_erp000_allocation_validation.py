"""Non-posting receipt/bill allocation validation and legacy bill safeguards."""
from datetime import date

import pytest

from ledgerone.models.core import Organisation
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
