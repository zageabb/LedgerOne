"""Receipt-to-bill allocation read model: schema, quantities and tenant isolation."""
from datetime import date

import pytest
from sqlalchemy import inspect

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.models import PurchaseReceiptBillAllocation
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.commercial.receipt_allocations import PurchaseReceiptAllocationService
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 17)


def _receipt():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    accounts = {account.code: account.id for account in Account.query.filter_by(
        organisation_id=organisation.id).all()}
    supplier = PurchasesService.create_supplier(context, name="Receipt allocation supplier")
    order = MultiLineOrderService.create(
        context, kind="purchase", party_id=supplier.id,
        order_number="PO-RECEIPT-ALLOC", order_date=DAY,
        expected_date=None, control_account_id=accounts["2100"],
        lines=[{"description": "Material", "quantity": "5", "unit_price": "12",
                "account_id": accounts["5000"], "item_treatment": "stock"}])
    PurchaseOrderService.set_status(context, order.id, status="approved")
    receipt = CommercialDocumentService.create(
        context, document_type="grn", order_id=order.id,
        document_date=DAY,
        lines=[{"order_line_id": order.lines[0].id, "quantity": "2"}])
    return context, order, receipt


def test_allocations_schema_and_empty_read_model_are_nonposting(app):
    with app.app_context():
        context, order, receipt = _receipt()
        columns = {column["name"] for column in inspect(db.engine).get_columns(
            "purchase_receipt_bill_allocations")}
        assert {"organisation_id", "purchase_order_line_id", "receipt_line_id",
                "bill_line_id", "quantity", "receipt_cost", "invoice_net"} <= columns
        assert PurchaseReceiptBillAllocation.query.count() == 0
        before = Journal.query.count()
        result = PurchaseReceiptAllocationService.summary(context, order_id=order.id)
        assert result["preview_only"] is True
        assert result["posting_authorised"] is False
        assert result["invalid_allocation_ids"] == []
        assert result["lines"][0]["ordered_quantity"] == "5.0000"
        assert result["lines"][0]["received_quantity"] == "2.0000"
        assert result["lines"][0]["allocated_invoice_quantity"] == "0"
        assert result["lines"][0]["remaining_received_quantity"] == "2.0000"
        assert Journal.query.count() == before


def test_allocation_summary_is_company_scoped(app):
    with app.app_context():
        context, order, receipt = _receipt()
        other = AccessContext.system("not-this-company")
        with pytest.raises(ValueError, match="Purchase order not found"):
            PurchaseReceiptAllocationService.summary(other, order_id=order.id)
        with pytest.raises(ValueError, match="Purchase order not found"):
            PurchaseReceiptAllocationService.summary(context, order_id="missing")
