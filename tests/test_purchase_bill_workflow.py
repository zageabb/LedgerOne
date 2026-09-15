from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.ai.tools import TOOLS
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.posting import can_post_action
from ledgerone.modules.workflows.purchase_bill_requests import PurchaseBillWorkflowService
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
        permissions=frozenset(permissions or {
            "purchases.read",
            "purchases.write",
            "workflows.read",
            "workflows.review",
            "workflows.post",
        }),
    )


def _accounts(context):
    return {
        row.code: row
        for row in Account.query.filter_by(organisation_id=context.organisation_id).all()
    }


def _supplier(context, name="Workflow Supplier"):
    return PurchasesService.create_supplier(context, name=name)


def _request(context, supplier, accounts, number="WF-BILL-001", amount="100.00"):
    return PurchaseBillWorkflowService.create_request(
        context,
        supplier_id=supplier.id,
        bill_number=number,
        bill_date=date(2026, 9, 15),
        due_date=date(2026, 10, 15),
        description="Workflow purchase",
        amount=amount,
        payable_account_id=accounts["2100"].id,
        expense_account_id=accounts["5000"].id,
        currency="GBP",
    )


def test_professional_purchase_bill_is_reviewed_before_ap_posting(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        supplier = _supplier(context)
        bills_before = PurchaseBill.query.count()
        journals_before = Journal.query.count()

        workflow = _request(context, supplier, accounts)

        assert workflow.status == "awaiting_review"
        assert PurchaseBill.query.count() == bills_before
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

        bill = PurchaseBillWorkflowService.post_from_action(context, post_action.id)

        assert PurchaseBill.query.count() == bills_before + 1
        assert Journal.query.count() == journals_before + 1
        assert bill.bill_number == "WF-BILL-001"
        assert bill.status == "posted"
        assert bill.posted_journal.source_module == "purchases"
        assert bill.metadata_json["workflow_instance_id"] == workflow.id
        workflow = db.session.get(WorkflowInstance, workflow.id)
        assert workflow.status == "posted"
        assert workflow.metadata_json["posted_purchase_bill_id"] == bill.id


def test_home_purchase_bill_still_requires_explicit_post(app):
    with app.app_context():
        context = _context(professional=False)
        accounts = _accounts(context)
        supplier = _supplier(context, "Home Supplier")
        bills_before = PurchaseBill.query.count()

        workflow = _request(context, supplier, accounts, number="WF-HOME-BILL")

        assert workflow.status == "ready_to_post"
        assert PurchaseBill.query.count() == bills_before
        assert UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="post",
            status="open",
        ).count() == 1


def test_open_workflow_reserves_purchase_bill_number(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        supplier = _supplier(context, "Duplicate Supplier")
        _request(context, supplier, accounts, number="WF-DUP-001")

        with pytest.raises(WorkflowError, match="open workflow"):
            _request(context, supplier, accounts, number="WF-DUP-001")
        assert PurchaseBill.query.filter_by(bill_number="WF-DUP-001").count() == 0


def test_ai_purchase_bill_is_proposed_not_posted(app):
    with app.app_context():
        context = _context(
            professional=True,
            permissions={"ai.use", "purchases.read", "purchases.write"},
        )
        accounts = _accounts(context)
        supplier = _supplier(context, "AI Supplier")
        bills_before = PurchaseBill.query.count()
        journals_before = Journal.query.count()

        result = TOOLS["purchases.create_bill"].handler(
            context,
            {
                "supplier_id": supplier.id,
                "bill_number": "WF-AI-BILL",
                "bill_date": "2026-09-15",
                "due_date": "2026-10-15",
                "description": "AI proposed purchase",
                "amount": "85.00",
                "payable_account_id": accounts["2100"].id,
                "expense_account_id": accounts["5000"].id,
                "currency": "GBP",
            },
        )

        assert result["posted"] is False
        assert result["status"] == "awaiting_review"
        assert PurchaseBill.query.count() == bills_before
        assert Journal.query.count() == journals_before
        workflow = db.session.get(WorkflowInstance, result["workflow_instance_id"])
        assert workflow.source_module == "ai"
        assert workflow.metadata_json["proposal_source_module"] == "ai"
