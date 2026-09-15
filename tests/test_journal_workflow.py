from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.ai.tools import TOOLS
from ledgerone.modules.workflows.journal_requests import JournalWorkflowService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.services import WorkflowService
from ledgerone.services.context import AccessContext
from ledgerone.services.control_accounts import ControlAccountError


def _setup(*, professional: bool):
    organisation = Organisation.query.first()
    user = User.query.first()
    user.ui_mode = "professional" if professional else "home"
    db.session.commit()
    context = AccessContext(
        identity_type="user",
        organisation_id=organisation.id,
        user_id=user.id,
        full_access=True,
        permissions=frozenset({"*"}),
    )
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return context, accounts


def _lines(accounts, amount="125.00"):
    return [
        {
            "account_id": accounts["1000"].id,
            "debit": amount,
            "credit": 0,
            "description": "Bank side",
        },
        {
            "account_id": accounts["4000"].id,
            "debit": 0,
            "credit": amount,
            "description": "Income side",
        },
    ]


def test_home_manual_journal_creates_post_action_without_posting(app):
    with app.app_context():
        context, accounts = _setup(professional=False)
        before = Journal.query.count()

        workflow = JournalWorkflowService.create_request(
            context,
            journal_date=date(2026, 9, 15),
            description="Home manual journal",
            reference="HOME-JNL",
            lines=_lines(accounts),
        )

        assert workflow.entity_type == "journal"
        assert workflow.status == "ready_to_post"
        assert Journal.query.count() == before
        action = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="post",
            status="open",
        ).one()

        journal = JournalWorkflowService.post_from_action(context, action.id)

        assert Journal.query.count() == before + 1
        assert journal.reference == "HOME-JNL"
        assert journal.source_module == "ledger"
        assert journal.total_debit == Decimal("125.00")
        assert journal.total_credit == Decimal("125.00")
        assert workflow.status == "posted"
        assert workflow.metadata_json["posted_journal_id"] == journal.id


def test_professional_manual_journal_requires_review_before_post(app):
    with app.app_context():
        context, accounts = _setup(professional=True)
        before = Journal.query.count()

        workflow = JournalWorkflowService.create_request(
            context,
            journal_date=date(2026, 9, 15),
            description="Professional manual journal",
            reference="PRO-JNL",
            lines=_lines(accounts, "250.00"),
        )

        assert workflow.status == "awaiting_review"
        assert Journal.query.count() == before
        review = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="review",
            status="open",
        ).one()

        WorkflowService.complete_action(context, review.id, decision="approve")
        workflow = db.session.get(WorkflowInstance, workflow.id)
        assert workflow.status == "ready_to_post"
        assert Journal.query.count() == before

        post_action = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="post",
            status="open",
        ).one()
        journal = JournalWorkflowService.post_from_action(context, post_action.id)
        assert journal.reference == "PRO-JNL"
        assert Journal.query.count() == before + 1


def test_manual_journal_control_account_is_rejected_before_workflow(app):
    with app.app_context():
        context, accounts = _setup(professional=True)
        before_workflows = WorkflowInstance.query.count()
        with pytest.raises(ControlAccountError, match="control account"):
            JournalWorkflowService.create_request(
                context,
                journal_date=date(2026, 9, 15),
                description="Bad direct AR journal",
                lines=[
                    {"account_id": accounts["1200"].id, "debit": "100.00", "credit": 0},
                    {"account_id": accounts["4000"].id, "debit": 0, "credit": "100.00"},
                ],
            )
        assert WorkflowInstance.query.count() == before_workflows


def test_ai_journal_tool_submits_for_workflow_instead_of_posting(app):
    with app.app_context():
        context, accounts = _setup(professional=True)
        before = Journal.query.count()

        result = TOOLS["ledger.post_journal"].handler(
            context,
            {
                "date": "2026-09-15",
                "description": "AI proposed journal",
                "reference": "AI-JNL",
                "lines": _lines(accounts, "75.00"),
            },
        )

        assert result["posted"] is False
        assert result["status"] == "awaiting_review"
        assert Journal.query.count() == before
        workflow = db.session.get(WorkflowInstance, result["workflow_instance_id"])
        assert workflow.source_module == "ai"
        assert workflow.metadata_json["journal_request"]["source_module"] == "ai"
        assert UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="review",
            status="open",
        ).count() == 1
