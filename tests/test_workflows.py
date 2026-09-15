from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.workflows.models import ScheduledTransaction, UserAction, WorkflowInstance
from ledgerone.modules.workflows.services import (
    RecurringTransactionService,
    WorkflowError,
    WorkflowService,
)
from ledgerone.services.context import AccessContext


def _context_and_accounts(*, professional=False):
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
    return context, user, accounts


def test_home_monthly_income_generates_work_item_and_posts_only_on_action(app):
    with app.app_context():
        context, _, accounts = _context_and_accounts(professional=False)
        template = RecurringTransactionService.create_template(
            context,
            name="Monthly Salary",
            description="Salary",
            transaction_type="income",
            amount_mode="expected",
            expected_amount="2300.00",
            tolerance="200.00",
            bank_account_id=accounts["1000"].id,
            counter_account_id=accounts["4000"].id,
            frequency="monthly",
            next_run_date=date(2026, 10, 1),
            reference="SALARY",
        )
        before = Journal.query.count()

        generated = RecurringTransactionService.generate_due(
            context, through_date=date(2026, 10, 1)
        )

        assert len(generated) == 1
        item = generated[0]
        assert item.status == "ready_to_post"
        assert template.next_run_date == date(2026, 11, 1)
        assert Journal.query.count() == before
        post_action = UserAction.query.filter_by(
            workflow_instance_id=item.workflow_instance_id,
            action_type="post",
            status="open",
        ).one()

        posted = RecurringTransactionService.post_from_action(
            context,
            post_action.id,
            actual_amount="2317.40",
            posting_date=date(2026, 10, 1),
        )

        assert posted.status == "posted"
        assert posted.actual_amount == Decimal("2317.40")
        journal = db.session.get(Journal, posted.journal_id)
        assert journal is not None
        by_account = {line.account_id: line for line in journal.lines}
        assert by_account[accounts["1000"].id].debit == Decimal("2317.40")
        assert by_account[accounts["4000"].id].credit == Decimal("2317.40")


def test_professional_mode_requires_review_and_never_auto_posts(app):
    with app.app_context():
        context, _, accounts = _context_and_accounts(professional=True)
        template = RecurringTransactionService.create_template(
            context,
            name="Council Tax",
            transaction_type="expense",
            amount_mode="fixed",
            expected_amount="185.00",
            bank_account_id=accounts["1000"].id,
            counter_account_id=accounts["5000"].id,
            frequency="monthly",
            next_run_date=date(2026, 10, 1),
        )
        before = Journal.query.count()

        item = RecurringTransactionService.generate_due(
            context, through_date=date(2026, 10, 1)
        )[0]
        workflow = db.session.get(WorkflowInstance, item.workflow_instance_id)
        assert workflow.status == "awaiting_review"
        assert item.status == "awaiting_review"
        assert Journal.query.count() == before

        review = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="review",
            status="open",
        ).one()
        WorkflowService.complete_action(context, review.id, decision="approve")

        assert workflow.status == "ready_to_post"
        assert Journal.query.count() == before
        post_action = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="post",
            status="open",
        ).one()
        RecurringTransactionService.post_from_action(context, post_action.id)
        assert Journal.query.count() == before + 1
        assert template.posting_mode == "manual"


def test_approval_rule_enforces_maker_checker(app):
    with app.app_context():
        context, creator, accounts = _context_and_accounts(professional=True)
        organisation = Organisation.query.first()
        manager = User(email="manager@example.test", name="Manager", ui_mode="professional")
        manager.set_password("test-password")
        db.session.add(manager)
        db.session.flush()
        db.session.add(
            Membership(
                organisation_id=organisation.id,
                user_id=manager.id,
                role="manager",
                permissions=["workflows.read", "workflows.approve"],
            )
        )
        db.session.commit()

        definition = WorkflowService.create_definition(
            context,
            name="Manager approval",
            entity_type="scheduled_transaction",
            transaction_type="expense",
            review_required=False,
            approval_required=True,
            approval_role="manager",
            separate_approver=True,
            priority=10,
        )
        RecurringTransactionService.create_template(
            context,
            name="Insurance",
            transaction_type="expense",
            amount_mode="fixed",
            expected_amount="750.00",
            bank_account_id=accounts["1000"].id,
            counter_account_id=accounts["5000"].id,
            frequency="annual",
            next_run_date=date(2026, 10, 2),
            workflow_definition_id=definition.id,
        )
        item = RecurringTransactionService.generate_due(
            context, through_date=date(2026, 10, 2)
        )[0]
        approval = UserAction.query.filter_by(
            workflow_instance_id=item.workflow_instance_id,
            action_type="approve",
            status="open",
        ).one()
        assert approval.assigned_role == "manager"

        with pytest.raises(WorkflowError, match="creator cannot approve"):
            WorkflowService.complete_action(context, approval.id, decision="approve")
        db.session.rollback()

        manager_context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id=manager.id,
            permissions=frozenset({"workflows.read", "workflows.approve"}),
        )
        WorkflowService.complete_action(manager_context, approval.id, decision="approve")
        workflow = db.session.get(WorkflowInstance, item.workflow_instance_id)
        assert workflow.status == "ready_to_post"
        assert Journal.query.filter_by(source_module="workflows").count() == 0


def test_recurring_generation_is_idempotent(app):
    with app.app_context():
        context, _, accounts = _context_and_accounts()
        template = RecurringTransactionService.create_template(
            context,
            name="Broadband",
            transaction_type="expense",
            amount_mode="fixed",
            expected_amount="32.00",
            bank_account_id=accounts["1000"].id,
            counter_account_id=accounts["5100"].id,
            frequency="monthly",
            next_run_date=date(2026, 9, 1),
        )
        first = RecurringTransactionService.generate_due(
            context, through_date=date(2026, 11, 1)
        )
        second = RecurringTransactionService.generate_due(
            context, through_date=date(2026, 11, 1)
        )
        assert len(first) == 3
        assert second == []
        assert ScheduledTransaction.query.filter_by(template_id=template.id).count() == 3
        assert template.next_run_date == date(2026, 12, 1)


def test_control_accounts_cannot_be_used_as_simple_recurring_categories(app):
    with app.app_context():
        context, _, accounts = _context_and_accounts()
        with pytest.raises(WorkflowError, match="control account"):
            RecurringTransactionService.create_template(
                context,
                name="Bad AR income",
                transaction_type="income",
                amount_mode="fixed",
                expected_amount="100.00",
                bank_account_id=accounts["1000"].id,
                counter_account_id=accounts["1200"].id,
                frequency="monthly",
                next_run_date=date(2026, 10, 1),
            )
