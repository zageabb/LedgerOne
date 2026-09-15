from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.workflows.journal_requests import JournalWorkflowService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.purchase_bill_requests import PurchaseBillWorkflowService
from ledgerone.modules.workflows.revisions import WorkflowRevisionService
from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
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


def _return_open_review(context, workflow):
    review = UserAction.query.filter_by(
        workflow_instance_id=workflow.id,
        action_type="review",
        status="open",
    ).one()
    WorkflowService.complete_action(context, review.id, decision="return", comments="Please correct this")
    return UserAction.query.filter_by(
        workflow_instance_id=workflow.id,
        action_type="review",
        status="open",
    ).one()


def test_returned_sales_invoice_is_replaced_revalidated_and_reposted(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = SalesService.create_customer(context, name="Revision Customer")
        workflow = SalesInvoiceWorkflowService.create_request(
            context,
            customer_id=customer.id,
            invoice_number="REV-INV-001",
            invoice_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
            description="Original sale",
            amount="100.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
            currency="GBP",
        )
        returned_action = _return_open_review(context, workflow)
        invoices_before = SalesInvoice.query.count()
        journals_before = Journal.query.count()

        replacement = WorkflowRevisionService.revise_sales_invoice(
            context,
            returned_action.id,
            {
                "amount": "125.00",
                "description": "Corrected sale",
                "invoice_number": "REV-INV-001",
            },
            revision_source_module="test",
        )

        old = db.session.get(WorkflowInstance, workflow.id)
        assert old.status == "superseded"
        assert old.metadata_json["replaced_by_workflow_instance_id"] == replacement.id
        assert replacement.id != old.id
        assert replacement.status == "awaiting_review"
        assert replacement.metadata_json["replaces_workflow_instance_id"] == old.id
        assert replacement.metadata_json["sales_invoice_request"]["amount"] == "125.00"
        assert db.session.get(UserAction, returned_action.id).decision == "resubmitted"
        assert SalesInvoice.query.count() == invoices_before
        assert Journal.query.count() == journals_before

        review = UserAction.query.filter_by(
            workflow_instance_id=replacement.id,
            action_type="review",
            status="open",
        ).one()
        WorkflowService.complete_action(context, review.id, decision="approve")
        post = UserAction.query.filter_by(
            workflow_instance_id=replacement.id,
            action_type="post",
            status="open",
        ).one()
        invoice = SalesInvoiceWorkflowService.post_from_action(context, post.id)
        assert invoice.invoice_number == "REV-INV-001"
        assert str(invoice.subtotal) == "125.00"
        assert invoice.metadata_json["workflow_instance_id"] == replacement.id


def test_revised_sales_amount_reselects_higher_approval_rule(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = SalesService.create_customer(context, name="Threshold Customer")
        definition = WorkflowService.create_definition(
            context,
            name="High value sales approval",
            entity_type="sales_invoice",
            min_amount="500.00",
            review_required=True,
            approval_required=True,
            separate_approver=False,
            priority=10,
        )
        workflow = SalesInvoiceWorkflowService.create_request(
            context,
            customer_id=customer.id,
            invoice_number="REV-THRESHOLD",
            invoice_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
            description="Initially small",
            amount="100.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
            currency="GBP",
        )
        assert workflow.workflow_definition_id is None
        returned_action = _return_open_review(context, workflow)

        replacement = WorkflowRevisionService.revise_sales_invoice(
            context,
            returned_action.id,
            {"amount": "1000.00"},
            revision_source_module="test",
        )

        assert replacement.workflow_definition_id == definition.id
        review = UserAction.query.filter_by(
            workflow_instance_id=replacement.id,
            action_type="review",
            status="open",
        ).one()
        WorkflowService.complete_action(context, review.id, decision="approve")
        assert db.session.get(WorkflowInstance, replacement.id).status == "awaiting_approval"
        assert UserAction.query.filter_by(
            workflow_instance_id=replacement.id,
            action_type="approve",
            status="open",
        ).count() == 1
        assert SalesInvoice.query.filter_by(invoice_number="REV-THRESHOLD").count() == 0


def test_invalid_sales_revision_rolls_back_returned_history(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = SalesService.create_customer(context, name="Rollback Customer")
        workflow = SalesInvoiceWorkflowService.create_request(
            context,
            customer_id=customer.id,
            invoice_number="REV-ROLLBACK",
            invoice_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
            description="Needs correction",
            amount="50.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
            currency="GBP",
        )
        returned_action = _return_open_review(context, workflow)
        count_before = WorkflowInstance.query.count()

        with pytest.raises(WorkflowError, match="greater than zero"):
            WorkflowRevisionService.revise_sales_invoice(
                context,
                returned_action.id,
                {"amount": "0"},
                revision_source_module="test",
            )

        old = db.session.get(WorkflowInstance, workflow.id)
        action = db.session.get(UserAction, returned_action.id)
        assert old.status == "returned"
        assert "replaced_by_workflow_instance_id" not in (old.metadata_json or {})
        assert old.metadata_json["sales_invoice_request"]["invoice_number"] == "REV-ROLLBACK"
        assert action.status == "open"
        assert WorkflowInstance.query.count() == count_before


def test_returned_purchase_bill_replacement_creates_no_ap_until_post(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        supplier = PurchasesService.create_supplier(context, name="Revision Supplier")
        workflow = PurchaseBillWorkflowService.create_request(
            context,
            supplier_id=supplier.id,
            bill_number="REV-BILL-001",
            bill_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
            description="Original bill",
            amount="80.00",
            payable_account_id=accounts["2100"].id,
            expense_account_id=accounts["5000"].id,
            currency="GBP",
        )
        returned_action = _return_open_review(context, workflow)
        bills_before = PurchaseBill.query.count()
        journals_before = Journal.query.count()

        replacement = WorkflowRevisionService.revise_purchase_bill(
            context,
            returned_action.id,
            {"amount": "95.00", "description": "Corrected bill"},
            revision_source_module="test",
        )

        assert db.session.get(WorkflowInstance, workflow.id).status == "superseded"
        assert replacement.status == "awaiting_review"
        assert replacement.metadata_json["purchase_bill_request"]["amount"] == "95.00"
        assert PurchaseBill.query.count() == bills_before
        assert Journal.query.count() == journals_before


def test_returned_journal_replacement_rebalances_and_stays_unposted(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        workflow = JournalWorkflowService.create_request(
            context,
            journal_date=date(2026, 9, 15),
            description="Original journal",
            reference="REV-JNL",
            lines=[
                {"account_id": accounts["1000"].id, "debit": "20.00", "credit": 0},
                {"account_id": accounts["4000"].id, "debit": 0, "credit": "20.00"},
            ],
        )
        returned_action = _return_open_review(context, workflow)
        journals_before = Journal.query.count()

        replacement = WorkflowRevisionService.revise_journal(
            context,
            returned_action.id,
            {
                "description": "Corrected journal",
                "lines": [
                    {"account_id": accounts["1000"].id, "debit": "35.00", "credit": 0},
                    {"account_id": accounts["4000"].id, "debit": 0, "credit": "35.00"},
                ],
            },
            revision_source_module="test",
        )

        assert db.session.get(WorkflowInstance, workflow.id).status == "superseded"
        assert replacement.status == "awaiting_review"
        assert str(replacement.amount) == "35.00"
        assert replacement.metadata_json["journal_request"]["description"] == "Corrected journal"
        assert Journal.query.count() == journals_before


def test_api_can_revise_returned_sales_proposal_without_posting(app, client):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = SalesService.create_customer(context, name="API Revision Customer")
        workflow = SalesInvoiceWorkflowService.create_request(
            context,
            customer_id=customer.id,
            invoice_number="REV-API-INV",
            invoice_date=date(2026, 9, 15),
            due_date=date(2026, 10, 15),
            description="API revision",
            amount="60.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
            currency="GBP",
        )
        returned_action = _return_open_review(context, workflow)
        organisation = Organisation.query.first()
        key, token = ApiKey.issue(
            name="workflow-revision-api",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        action_id = returned_action.id
        invoice_count = SalesInvoice.query.count()
        journal_count = Journal.query.count()

    response = client.post(
        f"/api/v1/workflows/actions/{action_id}/revise",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": "70.00", "description": "API corrected"},
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["replacement"]["status"] == "awaiting_review"
    assert data["replaces_workflow_instance_id"] == workflow.id
    with app.app_context():
        assert SalesInvoice.query.count() == invoice_count
        assert Journal.query.count() == journal_count
