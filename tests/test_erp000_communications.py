"""Contact purpose routing and non-sending document email draft tests."""
from datetime import date

import pytest

from ledgerone.models.core import Organisation, User
from ledgerone.models.ledger import Account
from ledgerone.modules.commercial.communications import CommercialCommunicationService
from ledgerone.modules.commercial.models import CommercialMessageDraft
from ledgerone.modules.commercial.services import CommercialDocumentService
from ledgerone.modules.purchases.orders import PurchaseOrderService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext

DAY = date(2026, 11, 17)


def _context_and_po():
    organisation = Organisation.query.one()
    person = User.query.first()
    context = AccessContext(identity_type="user", organisation_id=organisation.id,
                            user_id=person.id, full_access=True)
    accounts = {row.code: row.id for row in Account.query.filter_by(
        organisation_id=organisation.id).all()}
    supplier = PurchasesService.create_supplier(context, name="Emails supplier")
    po = PurchaseOrderService.create_order(
        context, supplier_id=supplier.id, order_number="PO-EMAIL-001",
        order_date=DAY, expected_date=None, description="Office supplies",
        amount="100.00", payable_account_id=accounts["2100"],
        expense_account_id=accounts["5000"])
    PurchaseOrderService.set_status(context, po.id, status="approved")
    ack = CommercialDocumentService.create(
        context, document_type="po_ack", order_id=po.id, document_date=DAY)
    return context, supplier, ack


def test_supplier_orders_contact_routing_previews_without_sending(app):
    with app.app_context():
        context, supplier, doc = _context_and_po()
        with pytest.raises(ValueError, match="No configured ORDERS"):
            CommercialCommunicationService.draft_document_email(
                context, document_id=doc.id, idempotency_key="request-001")
        CommercialCommunicationService.add_route(
            context, party_type="supplier", party_id=supplier.id,
            purpose="ORDERS", email="purchasing@supplier.example", contact_name="Orders")
        CommercialCommunicationService.add_route(
            context, party_type="supplier", party_id=supplier.id,
            purpose="ACCOUNTS", email="ap@supplier.example")
        message = CommercialCommunicationService.draft_document_email(
            context, document_id=doc.id, idempotency_key="request-001",
            subject="Purchase order acknowledgement requested")
        assert message.recipients_json == ["purchasing@supplier.example"]
        assert message.status == "draft"
        assert message.subject == "Purchase order acknowledgement requested"
        assert CommercialCommunicationService.draft_document_email(
            context, document_id=doc.id, idempotency_key="request-001").id == message.id
        assert CommercialMessageDraft.query.count() == 1


def test_contact_routes_never_cross_companies_or_roles(app):
    with app.app_context():
        context, supplier, doc = _context_and_po()
        other = AccessContext(identity_type="user", organisation_id="other-company",
                              user_id=context.user_id, full_access=True)
        with pytest.raises(ValueError, match="not found in company"):
            CommercialCommunicationService.add_route(
                other, party_type="supplier", party_id=supplier.id,
                purpose="ORDERS", email="one@supplier.example")
        with pytest.raises(ValueError, match="Document not found in company"):
            CommercialCommunicationService.draft_document_email(
                other, document_id=doc.id, idempotency_key="cross-company")
        with pytest.raises(ValueError, match="Invalid contact purpose"):
            CommercialCommunicationService.add_route(
                context, party_type="supplier", party_id=supplier.id,
                purpose="PASSWORD", email="someone@supplier.example")
        with pytest.raises(ValueError, match="Valid email"):
            CommercialCommunicationService.add_route(
                context, party_type="supplier", party_id=supplier.id,
                purpose="ORDERS", email="not-an-email")
