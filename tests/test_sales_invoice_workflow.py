from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.ai.tools import TOOLS
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.posting import can_post_action
from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.context import AccessContext


def _context(*, professional=True, permissions=None):
    organisation = Organisation.query.first()
    user = User.query.first()
    user.ui_mode = "professional" if professional else "home"
    db.session.commit()
    return AccessContext(
        identity_type="user",
        organisation_id=organisation.id,
        user_id=user.id,
        permissions=frozenset(
            permissions
            or {
                "sales.read",
                "sales.write",
                "workflows.read",
                "workflows.review",
                "workflows.post",
            }
        ),
    )


def _accounts(context):
    return {
        row.code: row
        for row in Account.query.filter_by(organisation_id=context.organisation_id).all()
    }


def _customer(context, name="Workflow Customer"):
    return SalesService.create_customer(context, name=name)


def _request(context, customer, accounts, number="WF-INV-001", amount="100.00"):
    return SalesInvoiceWorkflowService.create_request(
        context,
        customer_id=customer.id,
        invoice_number=number,
        invoice_date=date(2026, 9, 15),
        due_date=date(2026, 10, 15),
        description="Workflow sale",
        amount=amount,
        receivable_account_id=accounts["1200"].id,
        revenue_account_id=accounts["4000"].id,
        currency="GBP",
    )


def test_professional_sales_invoice_is_reviewed_before_ar_posting(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        customer = _customer(context)
        invoices_before = SalesInvoice.query.count()
        journals_before = Journal.query.count()

        workflow = _request(context, customer, accounts)

        assert workflow.status == "awaiting_review"
        assert SalesInvoice.query.count() == invoices_before
        assert Journal.query.count() == journals_before
        review = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="review",
            status="open",
        ).one()

        WorkflowService.complete_action(context, review.id, decision="approve")
        post_action = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="post",
            status="open",
        ).one()
        assert can_post_action(context, post_action) is True
        assert context.can("ledger.journals.post") is False

        invoice = SalesInvoiceWorkflowService.post_from_action(context, post_action.id)

        assert SalesInvoice.query.count() == invoices_before + 1
        assert Journal.query.count() == journals_before + 1
        assert invoice.invoice_number == "WF-INV-001"
        assert invoice.status == "posted"
        assert invoice.posted_journal.source_module == "sales"
        assert invoice.metadata_json["workflow_instance_id"] == workflow.id
        workflow = db.session.get(WorkflowInstance, workflow.id)
        assert workflow.status == "posted"
        assert workflow.metadata_json["posted_sales_invoice_id"] == invoice.id


def test_home_sales_invoice_still_requires_explicit_post(app):
    with app.app_context():
        context = _context(professional=False)
        accounts = _accounts(context)
        customer = _customer(context, "Home Customer")
        invoices_before = SalesInvoice.query.count()

        workflow = _request(context, customer, accounts, number="WF-HOME-INV")

        assert workflow.status == "ready_to_post"
        assert SalesInvoice.query.count() == invoices_before
        assert UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="post",
            status="open",
        ).count() == 1


def test_open_workflow_reserves_sales_invoice_number(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        customer = _customer(context, "Duplicate Customer")
        _request(context, customer, accounts, number="WF-DUP-INV")

        with pytest.raises(WorkflowError, match="open workflow"):
            _request(context, customer, accounts, number="WF-DUP-INV")
        assert SalesInvoice.query.filter_by(invoice_number="WF-DUP-INV").count() == 0


def test_ai_sales_invoice_is_proposed_not_posted(app):
    with app.app_context():
        context = _context(
            professional=True,
            permissions={"ai.use", "sales.read", "sales.write"},
        )
        accounts = _accounts(context)
        customer = _customer(context, "AI Customer")
        invoices_before = SalesInvoice.query.count()
        journals_before = Journal.query.count()

        result = TOOLS["sales.create_invoice"].handler(
            context,
            {
                "customer_id": customer.id,
                "invoice_number": "WF-AI-INV",
                "invoice_date": "2026-09-15",
                "due_date": "2026-10-15",
                "description": "AI proposed sale",
                "amount": "85.00",
                "receivable_account_id": accounts["1200"].id,
                "revenue_account_id": accounts["4000"].id,
                "currency": "GBP",
            },
        )

        assert result["posted"] is False
        assert result["status"] == "awaiting_review"
        assert SalesInvoice.query.count() == invoices_before
        assert Journal.query.count() == journals_before
        workflow = db.session.get(WorkflowInstance, result["workflow_instance_id"])
        assert workflow.source_module == "ai"
        assert workflow.metadata_json["proposal_source_module"] == "ai"
