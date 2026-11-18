"""Receipt-to-bill allocation read model: schema, quantities and tenant isolation."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.models import PurchaseReceiptBillAllocation
from ledgerone.modules.commercial.order_builder import MultiLineOrderService
from ledgerone.modules.commercial.receipt_allocations import (
    PurchaseReceiptAllocationService, _inspect_allocation_evidence,
)
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
        assert result["overallocated_receipt_line_ids"] == []
        assert result["allocation_evidence_valid"] is True
        assert result["quantity_available_for_posting_certified"] is False
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


def test_receipt_allocation_read_only_api_registered(app):
    with app.app_context():
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        assert "commercial_api.purchase_receipt_allocations" in endpoints


def test_allocation_evidence_rejects_wrong_receipt_owner_and_overallocation():
    quantities = {"po-a": Decimal("5"), "po-b": Decimal("5")}
    owners = {"grn-a": "po-a", "grn-b": "po-b"}
    received = {"grn-a": Decimal("2"), "grn-b": Decimal("3")}
    rows = [
        SimpleNamespace(id="ok", receipt_line_id="grn-a",
                        purchase_order_line_id="po-a", quantity=Decimal("1")),
        SimpleNamespace(id="wrong-owner", receipt_line_id="grn-a",
                        purchase_order_line_id="po-b", quantity=Decimal("1")),
        SimpleNamespace(id="missing-grn", receipt_line_id="unknown",
                        purchase_order_line_id="po-a", quantity=Decimal("1")),
        SimpleNamespace(id="over-grn", receipt_line_id="grn-a",
                        purchase_order_line_id="po-a", quantity=Decimal("2")),
    ]
    allocated, invalid, over_receipts, over_lines = _inspect_allocation_evidence(
        quantities, owners, received, rows,
    )
    assert allocated == {"po-a": Decimal("3"), "po-b": Decimal("0")}
    assert invalid == ["missing-grn", "wrong-owner"]
    assert over_receipts == ["grn-a"]
    assert over_lines == set()


def test_allocation_evidence_detects_order_line_overallocation():
    rows = [
        SimpleNamespace(id="a", receipt_line_id="grn-1",
                        purchase_order_line_id="po", quantity=Decimal("3")),
        SimpleNamespace(id="b", receipt_line_id="grn-2",
                        purchase_order_line_id="po", quantity=Decimal("3")),
    ]
    allocated, invalid, over_receipts, over_lines = _inspect_allocation_evidence(
        {"po": Decimal("5")},
        {"grn-1": "po", "grn-2": "po"},
        {"grn-1": Decimal("4"), "grn-2": Decimal("4")},
        rows,
    )
    assert allocated["po"] == Decimal("6")
    assert invalid == []
    assert over_receipts == []
    assert over_lines == {"po"}
