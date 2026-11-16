"""Direct manual journal approval gates and strict approver assignment."""
from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.workflows.journal_requests import JournalWorkflowService
from ledgerone.modules.workflows.models import UserAction
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.company import CompanyService
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError, LedgerService


POSTING_DATE = date(2026, 11, 16)


def _owner():
    org = Organisation.query.one()
    user = User.query.one()
    user.ui_mode = "home"
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org.id, user_id=user.id,
                         full_access=True, permissions=frozenset({"*"}))


def _user_context(org_id, *, role, email, full_access=False):
    person = User(email=email, name=email, ui_mode="professional")
    person.set_password("secure-test-password")
    db.session.add(person)
    db.session.flush()
    db.session.add(Membership(organisation_id=org_id, user_id=person.id, role=role,
                              permissions=["workflows.read", "workflows.approve"]))
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org_id, user_id=person.id,
                         full_access=full_access, permissions=frozenset({"workflows.read", "workflows.approve"}))


def _lines(org_id, amount="100.00"):
    accounts = {a.code: a for a in Account.query.filter_by(organisation_id=org_id).all()}
    return [{"account_id": accounts["1000"].id, "debit": amount, "credit": "0.00"},
            {"account_id": accounts["4000"].id, "debit": "0.00", "credit": amount}]


def test_threshold_blocks_direct_post_but_allows_separately_approved_journal(app):
    with app.app_context():
        maker = _owner()
        checker = _user_context(maker.organisation_id, role="manager",
                                email="checker-direct@example.test")
        WorkflowService.set_approval_policy(maker, enabled=True, threshold="100.00",
                                            approval_role="manager")
        lines = _lines(maker.organisation_id)
        starting = Journal.query.count()

        with pytest.raises(LedgerError, match="Company approval required"):
            LedgerService.post_journal(maker, journal_date=POSTING_DATE,
                                       description="Direct", lines=lines)
        db.session.rollback()
        assert Journal.query.count() == starting

        low = LedgerService.post_journal(maker, journal_date=POSTING_DATE,
                                         description="Small journal", lines=_lines(maker.organisation_id, "99.99"))
        assert low.total_debit == 99.99
        assert Journal.query.count() == starting + 1

        workflow = JournalWorkflowService.create_request(
            maker, journal_date=POSTING_DATE, description="Approved journal", lines=lines)
        approval = UserAction.query.filter_by(workflow_instance_id=workflow.id,
                                              action_type="approve", status="open").one()
        with pytest.raises(WorkflowError, match="creator cannot approve"):
            WorkflowService.complete_action(maker, approval.id, decision="approve")
        db.session.rollback()

        WorkflowService.complete_action(checker, approval.id, decision="approve")
        post = UserAction.query.filter_by(workflow_instance_id=workflow.id,
                                          action_type="post", status="open").one()
        journal = JournalWorkflowService.post_from_action(maker, post.id)
        assert journal.total_debit == 100.00
        assert Journal.query.count() == starting + 2
        with pytest.raises(WorkflowError, match="not found"):
            JournalWorkflowService.post_from_action(maker, post.id)


def test_approved_workflow_cannot_be_used_to_post_changed_or_cross_company_journal(app):
    with app.app_context():
        maker = _owner()
        checker = _user_context(maker.organisation_id, role="manager",
                                email="checker-content@example.test")
        WorkflowService.set_approval_policy(maker, enabled=True, threshold="100.00")
        lines = _lines(maker.organisation_id)
        workflow = JournalWorkflowService.create_request(
            maker, journal_date=POSTING_DATE, description="Protected", lines=lines)
        approval = UserAction.query.filter_by(workflow_instance_id=workflow.id,
                                              action_type="approve").one()
        WorkflowService.complete_action(checker, approval.id, decision="approve")

        with pytest.raises(LedgerError, match="does not match"):
            LedgerService.post_journal(maker, journal_date=POSTING_DATE,
                description="Changed", lines=list(reversed(lines)),
                approved_workflow_id=workflow.id)
        db.session.rollback()

        second = CompanyService.create(maker, name="Other Ledger", company_code="OTHER")
        company_two = AccessContext(identity_type="user", user_id=maker.user_id,
                                    organisation_id=second.id, full_access=True)
        WorkflowService.set_approval_policy(company_two, enabled=True, threshold="100.00")
        with pytest.raises(LedgerError, match="Company approval required"):
            LedgerService.post_journal(company_two, journal_date=POSTING_DATE,
                description="Other company", lines=_lines(second.id),
                approved_workflow_id=workflow.id)
        db.session.rollback()


def test_assignment_and_role_bind_even_for_owner_permissions(app):
    with app.app_context():
        maker = _owner()
        manager = _user_context(maker.organisation_id, role="manager",
                                email="manager-assignment@example.test")
        other_owner = _user_context(maker.organisation_id, role="owner",
                                    email="owner-assignment@example.test", full_access=True)
        rule = WorkflowService.create_definition(
            maker, name="Manager checker", entity_type="external_item",
            review_required=False, approval_required=True, approval_role="manager")
        instance = WorkflowService.start(maker, entity_type="external_item",
            entity_id="assignment-1", title="Role-bound", amount="150.00", definition_id=rule.id)
        approval = UserAction.query.filter_by(workflow_instance_id=instance.id,
                                               action_type="approve", status="open").one()
        assert approval not in WorkflowService.open_actions(other_owner)
        with pytest.raises(PermissionError, match="assigned"):
            WorkflowService.complete_action(other_owner, approval.id, decision="approve")
        db.session.rollback()
        assert approval in WorkflowService.open_actions(manager)
        WorkflowService.complete_action(manager, approval.id, decision="approve")
        assert approval.completed_by_user_id == manager.user_id
