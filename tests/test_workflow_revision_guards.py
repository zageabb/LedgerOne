from datetime import date

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.revisions import WorkflowRevisionService
from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService
from ledgerone.modules.workflows.services import WorkflowService
from ledgerone.services.context import AccessContext


def _context():
    organisation = Organisation.query.first()
    user = User.query.first()
    user.ui_mode = "professional"
    db.session.commit()
    return AccessContext(
        identity_type="user",
        organisation_id=organisation.id,
        user_id=user.id,
        full_access=True,
        permissions=frozenset({"*"}),
    )


def _accounts(context):
    return {
        row.code: row
        for row in Account.query.filter_by(organisation_id=context.organisation_id).all()
    }


def _sales_workflow(context, *, number: str, amount: str = "100.00"):
    accounts = _accounts(context)
    customer = SalesService.create_customer(context, name=f"Customer {number}")
    return SalesInvoiceWorkflowService.create_request(
        context,
        customer_id=customer.id,
        invoice_number=number,
        invoice_date=date(2026, 9, 15),
        due_date=date(2026, 10, 15),
        description="Revision guard sale",
        amount=amount,
        receivable_account_id=accounts["1200"].id,
        revenue_account_id=accounts["4000"].id,
        currency="GBP",
    )


def _return(context, workflow):
    review = UserAction.query.filter_by(
        workflow_instance_id=workflow.id,
        action_type="review",
        status="open",
    ).one()
    WorkflowService.complete_action(
        context,
        review.id,
        decision="return",
        comments="Correction required",
    )
    return UserAction.query.filter_by(
        workflow_instance_id=workflow.id,
        action_type="review",
        status="open",
    ).one()


def _api_key(context):
    key, token = ApiKey.issue(
        name="revision-guard-api",
        organisation_id=context.organisation_id,
        full_access=True,
    )
    db.session.add(key)
    db.session.commit()
    return token


def test_api_cannot_approve_returned_payload_without_replacement(app, client):
    with app.app_context():
        context = _context()
        workflow = _sales_workflow(context, number="REV-STALE-001")
        returned_action = _return(context, workflow)
        token = _api_key(context)
        action_id = returned_action.id
        workflow_id = workflow.id
        invoice_count = SalesInvoice.query.count()
        journal_count = Journal.query.count()

    response = client.post(
        f"/api/v1/workflows/actions/{action_id}/decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "approve"},
    )

    assert response.status_code == 400
    assert "corrected and resubmitted" in response.get_json()["error"]
    with app.app_context():
        stored = db.session.get(WorkflowInstance, workflow_id)
        action = db.session.get(UserAction, action_id)
        assert stored.status == "returned"
        assert action.status == "open"
        assert SalesInvoice.query.count() == invoice_count
        assert Journal.query.count() == journal_count


def test_sales_invoice_number_survives_multiple_replacement_cycles(app):
    with app.app_context():
        context = _context()
        original = _sales_workflow(context, number="REV-CYCLE-001", amount="100.00")
        first_return = _return(context, original)

        first_replacement = WorkflowRevisionService.revise_sales_invoice(
            context,
            first_return.id,
            {"amount": "110.00"},
            revision_source_module="test",
        )
        second_return = _return(context, first_replacement)

        second_replacement = WorkflowRevisionService.revise_sales_invoice(
            context,
            second_return.id,
            {"amount": "120.00"},
            revision_source_module="test",
        )

        original = db.session.get(WorkflowInstance, original.id)
        first = db.session.get(WorkflowInstance, first_replacement.id)
        second = db.session.get(WorkflowInstance, second_replacement.id)
        assert original.status == "superseded"
        assert first.status == "superseded"
        assert second.status == "awaiting_review"
        assert second.metadata_json["sales_invoice_request"]["invoice_number"] == "REV-CYCLE-001"
        assert second.metadata_json["sales_invoice_request"]["amount"] == "120.00"
        assert SalesInvoice.query.filter_by(invoice_number="REV-CYCLE-001").count() == 0


def test_returned_sales_browser_renders_correction_form(app, client):
    with app.app_context():
        context = _context()
        workflow = _sales_workflow(context, number="REV-BROWSER-001")
        _return(context, workflow)

    login = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert login.status_code == 200
    page = client.get("/workflows/actions")
    assert page.status_code == 200
    assert b"Correct &amp; resubmit invoice" in page.data or b"Correct & resubmit invoice" in page.data
    assert b"REV-BROWSER-001" in page.data
    assert b"replacement workflow" in page.data
