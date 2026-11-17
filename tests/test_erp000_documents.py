"""ERP-000 initial operational document integration and quantity invariants."""
from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.commercial.models import CommercialDocument
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.orders import SalesOrderService
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext

TODAY = date(2026, 11, 17)


def _setup():
    org = Organisation.query.one()
    context = AccessContext.system(org.id)
    accounts = {a.code: a.id for a in Account.query.filter_by(
        organisation_id=org.id).all()}
    supplier = PurchasesService.create_supplier(context, name="Ack supplier")
    customer = SalesService.create_customer(context, name="Ack customer")
    purchase = PurchaseOrderService.create_order(
        context, supplier_id=supplier.id, order_number="PO-ERP-001",
        order_date=TODAY, expected_date=None, description="Five items",
        amount="100.00", payable_account_id=accounts["2100"],
        expense_account_id=accounts["5000"])
    sales = SalesOrderService.create_order(
        context, customer_id=customer.id, order_number="SO-ERP-001",
        order_date=TODAY, requested_delivery_date=None, description="Five items",
        amount="100.00", receivable_account_id=accounts["1200"],
        revenue_account_id=accounts["4000"])
    # Existing order services construct one line; set quantity to five without
    # changing net amount, to exercise partial receipt and dispatch protections.
    purchase.lines[0].quantity = Decimal("5")
    purchase.lines[0].unit_price = Decimal("20")
    sales.lines[0].quantity = Decimal("5")
    sales.lines[0].unit_price = Decimal("20")
    db.session.commit()
    return context, purchase, sales


def test_supplier_acknowledgement_and_partial_grn_without_posting(app):
    with app.app_context():
        context, purchase, sales = _setup()
        before_journals = Journal.query.count()
        with pytest.raises(ValueError, match="Order must be"):
            CommercialDocumentService.create(
                context, document_type="po_ack", order_id=purchase.id,
                document_date=TODAY)
        PurchaseOrderService.set_status(context, purchase.id, status="approved")
        acknowledged = CommercialDocumentService.create(
            context, document_type="po_ack", order_id=purchase.id,
            document_date=TODAY, external_reference="SUP-ACK-100")
        assert acknowledged.document_number == "POA-PO-ERP-001-001"
        assert acknowledged.lines[0].quantity == Decimal("5.0000")
        response = CommercialDocumentService.respond_to_po_ack(
            context, acknowledged.id, response_status="accepted",
            supplier_reference="SUP-ACK-100")
        assert response.response_status == "accepted"
        with pytest.raises(ValueError, match="already recorded"):
            CommercialDocumentService.respond_to_po_ack(
                context, acknowledged.id, response_status="accepted")

        order_line = purchase.lines[0].id
        receipt = CommercialDocumentService.create(
            context, document_type="grn", order_id=purchase.id,
            document_date=TODAY,
            lines=[{"order_line_id": order_line, "quantity": "2"}])
        receipt2 = CommercialDocumentService.create(
            context, document_type="grn", order_id=purchase.id,
            document_date=TODAY,
            lines=[{"order_line_id": order_line, "quantity": "3"}])
        assert receipt.document_number == "GRN-PO-ERP-001-001"
        assert receipt2.document_number == "GRN-PO-ERP-001-002"
        with pytest.raises(ValueError, match="exceeds outstanding"):
            CommercialDocumentService.create(
                context, document_type="grn", order_id=purchase.id,
                document_date=TODAY,
                lines=[{"order_line_id": order_line, "quantity": "0.1"}])
        assert len(CommercialDocumentService.list_for_order(
            context, document_type="grn", order_id=purchase.id)) == 2
        assert Journal.query.count() == before_journals


def test_sales_order_ack_and_multiple_delivery_notes(app):
    with app.app_context():
        context, purchase, sales = _setup()
        SalesOrderService.set_status(context, sales.id, status="confirmed")
        before_journals = Journal.query.count()
        ack = CommercialDocumentService.create(
            context, document_type="so_ack", order_id=sales.id,
            document_date=TODAY)
        assert ack.document_number == "SOA-SO-ERP-001-001"
        line_id = sales.lines[0].id
        for amount in ("1", "4"):
            CommercialDocumentService.create(
                context, document_type="delivery_note", order_id=sales.id,
                document_date=TODAY,
                lines=[{"order_line_id": line_id, "quantity": amount}])
        assert len(CommercialDocumentService.list_for_order(
            context, document_type="delivery_note", order_id=sales.id)) == 2
        with pytest.raises(ValueError, match="exceeds outstanding"):
            CommercialDocumentService.create(
                context, document_type="delivery_note", order_id=sales.id,
                document_date=TODAY,
                lines=[{"order_line_id": line_id, "quantity": "1"}])
        assert Journal.query.count() == before_journals


def test_rejects_cross_company_lines_and_document_lookups(app):
    with app.app_context():
        context, purchase, sales = _setup()
        PurchaseOrderService.set_status(context, purchase.id, status="approved")
        SalesOrderService.set_status(context, sales.id, status="confirmed")
        other = AccessContext.system("not-this-company")
        with pytest.raises(ValueError, match="Order not found"):
            CommercialDocumentService.create(
                other, document_type="grn", order_id=purchase.id,
                document_date=TODAY, lines=[
                    {"order_line_id": purchase.lines[0].id, "quantity": "1"}])
        with pytest.raises(ValueError, match="Order not found"):
            CommercialDocumentService.list_for_order(
                other, document_type="so_ack", order_id=sales.id)
        with pytest.raises(ValueError, match="unique line"):
            CommercialDocumentService.create(
                context, document_type="grn", order_id=purchase.id,
                document_date=TODAY,
                lines=[{"order_line_id": sales.lines[0].id, "quantity": "1"}])
        assert CommercialDocument.query.count() == 0
