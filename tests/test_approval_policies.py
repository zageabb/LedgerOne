from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.models.ledger import Account
from ledgerone.modules.workflows.journal_requests import JournalWorkflowService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.approval_policy import ApprovalPolicyService, ApprovalRequired
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService
from ledgerone.services.period_policy import PeriodPolicyService


def _maker_checker():
    organisation = Organisation.query.first()
    maker = User.query.first()
    maker.ui_mode = "professional"
    checker = User(email="checker@ledgerone.test", name="Checker", ui_mode="professional")
    checker.set_password("test-password")
    db.session.add(checker)
    db.session.flush()
    db.session.add(
        Membership(
            organisation_id=organisation.id,
            user_id=checker.id,
            role="manager",
            permissions=["workflows.read", "workflows.approve"],
            is_active=True,
        )
    )
    db.session.commit()
    maker_context = AccessContext(
        identity_type="user",
        organisation_id=organisation.id,
        user_id=maker.id,
        full_access=True,
        permissions=frozenset({"*"}),
    )
    checker_context = AccessContext(
        identity_type="user",
        organisation_id=organisation.id,
        user_id=checker.id,
        permissions=frozenset({"workflows.read", "workflows.approve"}),
    )
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return maker_context, checker_context, accounts


def _approve(checker_context, workflow, *, comments="Checked and approved"):
    action = UserAction.query.filter_by(
        workflow_instance_id=workflow.id,
        action_type="approve",
        status="open",
    ).one()
    WorkflowService.complete_action(
        checker_context,
        action.id,
        decision="approve",
        comments=comments,
    )
    return action


def test_master_data_policy_enforces_no_self_approval_and_consumes_history(app):
    with app.app_context():
        maker, checker, _ = _maker_checker()
        from ledgerone.modules.sales.services import SalesService

        ApprovalPolicyService.set(
            maker,
            "master_data",
            enabled=True,
            approval_role="manager",
            separate_approver=True,
        )

        with pytest.raises(ApprovalRequired) as required:
            SalesService.create_customer(maker, name="Controlled Customer")
        workflow = required.value.workflow
        action = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="approve",
            status="open",
        ).one()
        assert action.assigned_role == "manager"

        with pytest.raises(WorkflowError, match="creator cannot approve"):
            WorkflowService.complete_action(maker, action.id, decision="approve")
        db.session.rollback()

        action = _approve(checker, workflow, comments="Independent master-data check")
        customer = SalesService.create_customer(maker, name="Controlled Customer")

        assert customer.name == "Controlled Customer"
        workflow = db.session.get(WorkflowInstance, workflow.id)
        action = db.session.get(UserAction, action.id)
        assert workflow.status == "executed"
        assert workflow.metadata_json["approval_consumed_at"]
        assert action.decision == "approve"
        assert action.comments == "Independent master-data check"
        assert action.completed_by_user_id == checker.user_id
        assert action.completed_at is not None


def test_payment_threshold_routes_only_at_or_above_threshold(app):
    with app.app_context():
        maker, checker, _ = _maker_checker()
        ApprovalPolicyService.set(
            maker,
            "payment",
            enabled=True,
            threshold="100.00",
            approval_role="manager",
        )

        assert ApprovalPolicyService.guard(
            maker,
            "payment",
            payload={"payment_id": "small", "amount": "99.99"},
            title="Small payment",
            amount="99.99",
        ) is None

        with pytest.raises(ApprovalRequired) as required:
            ApprovalPolicyService.guard(
                maker,
                "payment",
                payload={"payment_id": "large", "amount": "100.00"},
                title="Large payment",
                amount="100.00",
            )
        workflow = required.value.workflow
        _approve(checker, workflow)
        authorised = ApprovalPolicyService.guard(
            maker,
            "payment",
            payload={"payment_id": "large", "amount": "100.00"},
            title="Large payment",
            amount="100.00",
        )
        assert authorised.id == workflow.id


def test_journal_policy_uses_threshold_and_separate_approver(app):
    with app.app_context():
        maker, checker, accounts = _maker_checker()
        ApprovalPolicyService.set(
            maker,
            "journal",
            enabled=True,
            threshold="100.00",
            approval_role="manager",
            separate_approver=True,
        )
        lines = [
            {"account_id": accounts["1000"].id, "debit": "125.00", "credit": 0},
            {"account_id": accounts["4000"].id, "debit": 0, "credit": "125.00"},
        ]
        workflow = JournalWorkflowService.create_request(
            maker,
            journal_date=date(2026, 9, 15),
            description="Threshold journal",
            lines=lines,
        )
        assert workflow.status == "awaiting_approval"
        approval = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="approve",
            status="open",
        ).one()
        assert approval.assigned_role == "manager"

        with pytest.raises(WorkflowError, match="creator cannot approve"):
            WorkflowService.complete_action(maker, approval.id, decision="approve")
        db.session.rollback()

        _approve(checker, workflow)
        assert db.session.get(WorkflowInstance, workflow.id).status == "ready_to_post"


def test_period_reopen_policy_requires_and_consumes_independent_approval(app):
    with app.app_context():
        maker, checker, _ = _maker_checker()
        period = LedgerService.create_period(
            maker,
            name="Approval period",
            start_date=date(2027, 1, 1),
            end_date=date(2027, 1, 31),
        )
        PeriodPolicyService.set_period_status(
            maker,
            period.id,
            status="hard_closed",
            reason="Month end complete",
        )
        ApprovalPolicyService.set(
            maker,
            "period_reopen",
            enabled=True,
            approval_role="manager",
            separate_approver=True,
        )

        with pytest.raises(ApprovalRequired) as required:
            PeriodPolicyService.set_period_status(
                maker,
                period.id,
                status="open",
                reason="Correction required",
            )
        workflow = required.value.workflow
        _approve(checker, workflow, comments="Reopen approved for correction")
        reopened = PeriodPolicyService.set_period_status(
            maker,
            period.id,
            status="open",
            reason="Correction required",
        )
        assert reopened.status == "open"
        assert db.session.get(WorkflowInstance, workflow.id).status == "executed"


def test_ai_write_policy_creates_generic_approval_request(app):
    with app.app_context():
        maker, checker, _ = _maker_checker()
        ApprovalPolicyService.set(
            maker,
            "ai_write",
            enabled=True,
            approval_role="manager",
            separate_approver=True,
        )
        payload = {
            "tool": "sales.create_customer",
            "arguments": {"name": "AI Controlled Customer"},
        }
        with pytest.raises(ApprovalRequired) as required:
            ApprovalPolicyService.guard(
                maker,
                "ai_write",
                payload=payload,
                title="Approve AI write: sales.create_customer",
            )
        workflow = required.value.workflow
        _approve(checker, workflow)
        authorised = ApprovalPolicyService.guard(
            maker,
            "ai_write",
            payload=payload,
            title="Approve AI write: sales.create_customer",
        )
        assert authorised.id == workflow.id



def test_customer_payment_policy_guards_real_service_and_consumes_approval(app):
    with app.app_context():
        maker, checker, accounts = _maker_checker()
        from ledgerone.modules.sales.services import SalesService

        customer = SalesService.create_customer(maker, name="Payment Customer")
        ApprovalPolicyService.set(
            maker,
            "payment",
            enabled=True,
            threshold="100.00",
            approval_role="manager",
        )

        kwargs = {
            "customer_id": customer.id,
            "payment_date": date(2026, 9, 15),
            "amount": "150.00",
            "bank_account_id": accounts["1000"].id,
            "receivable_account_id": accounts["1200"].id,
            "reference": "PAY-APPROVAL",
            "currency": "GBP",
        }
        with pytest.raises(ApprovalRequired) as required:
            SalesService.record_payment(maker, **kwargs)
        workflow = required.value.workflow
        assert SalesService.list_payments(maker) == []

        _approve(checker, workflow, comments="Payment independently approved")
        payment = SalesService.record_payment(maker, **kwargs)

        assert payment.amount == ApprovalPolicyService._money("150.00")
        assert db.session.get(WorkflowInstance, workflow.id).status == "executed"


def test_control_account_adjustment_policy_guards_posting(app):
    with app.app_context():
        maker, checker, accounts = _maker_checker()
        from ledgerone.services.control_accounts import ControlAccountService

        ApprovalPolicyService.set(
            maker,
            "control_adjustment",
            enabled=True,
            approval_role="manager",
        )
        kwargs = {
            "journal_date": date(2026, 9, 15),
            "description": "Approved AR correction",
            "reference": "CTRL-APP-1",
            "reason": "Independent correction evidence",
            "lines": [
                {"account_id": accounts["1200"].id, "debit": "10.00", "credit": 0},
                {"account_id": accounts["4000"].id, "debit": 0, "credit": "10.00"},
            ],
        }
        with pytest.raises(ApprovalRequired) as required:
            ControlAccountService.post_adjustment(maker, **kwargs)
        workflow = required.value.workflow

        _approve(checker, workflow)
        journal = ControlAccountService.post_adjustment(maker, **kwargs)

        assert journal.source_module == "control_adjustment"
        assert db.session.get(WorkflowInstance, workflow.id).status == "executed"
