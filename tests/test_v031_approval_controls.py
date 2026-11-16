"""v0.3.1 maker/checker and tenant approval-policy regressions."""
import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.company import CompanyService
from ledgerone.services.context import AccessContext


def _owner():
    org = Organisation.query.one()
    user = User.query.one()
    user.ui_mode = "home"
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org.id, user_id=user.id,
                         full_access=True, permissions=frozenset({"*"}))


def _second_user(org_id):
    checker = User(email="independent-checker@example.test", name="Checker", ui_mode="professional")
    checker.set_password("a-valid-test-password")
    db.session.add(checker)
    db.session.flush()
    db.session.add(Membership(organisation_id=org_id, user_id=checker.id,
                              role="manager", permissions=["workflows.read", "workflows.approve"]))
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org_id,
                         user_id=checker.id, permissions=frozenset({"workflows.read", "workflows.approve"}))


def test_company_threshold_requires_independent_approval_even_without_definition(app):
    with app.app_context():
        creator = _owner()
        checker = _second_user(creator.organisation_id)
        WorkflowService.set_approval_policy(creator, enabled=True, threshold="500.00",
                                            approval_role="manager")
        low = WorkflowService.start(creator, entity_type="external_item", entity_id="low",
                                    title="Low amount", amount="499.99")
        high = WorkflowService.start(creator, entity_type="external_item", entity_id="high",
                                     title="High amount", amount="500.00")
        assert low.status == "ready_to_post"
        assert high.status == "awaiting_approval"
        approval = UserAction.query.filter_by(workflow_instance_id=high.id,
                                              action_type="approve", status="open").one()
        assert approval.assigned_role == "manager"
        with pytest.raises(WorkflowError, match="creator cannot approve"):
            WorkflowService.complete_action(creator, approval.id, decision="approve")
        db.session.rollback()
        with pytest.raises(WorkflowError, match="signed-in individual"):
            WorkflowService.complete_action(
                AccessContext.system(creator.organisation_id), approval.id, decision="approve")
        db.session.rollback()
        WorkflowService.complete_action(checker, approval.id, decision="approve")
        assert db.session.get(WorkflowInstance, high.id).status == "ready_to_post"


def test_approval_step_cannot_be_removed_by_changing_rule(app):
    with app.app_context():
        creator = _owner()
        checker = _second_user(creator.organisation_id)
        rule = WorkflowService.create_definition(
            creator, name="Reviewed transaction", entity_type="external_item",
            review_required=True, approval_required=False)
        WorkflowService.set_approval_policy(creator, enabled=True, threshold="100.00")
        instance = WorkflowService.start(creator, entity_type="external_item",
                                         entity_id="snapshot-case", title="Reviewed",
                                         amount="150.00", definition_id=rule.id)
        first = UserAction.query.filter_by(workflow_instance_id=instance.id,
                                           action_type="review", status="open").one()
        rule.steps_json = []
        db.session.commit()
        WorkflowService.complete_action(creator, first.id, decision="approve")
        approval = UserAction.query.filter_by(workflow_instance_id=instance.id,
                                              action_type="approve", status="open").one()
        assert instance.status == "awaiting_approval"
        WorkflowService.complete_action(checker, approval.id, decision="approve")
        assert instance.status == "ready_to_post"


def test_approval_policy_is_isolated_and_permissions_enforced(app):
    with app.app_context():
        creator = _owner()
        second = CompanyService.create(creator, name="Second Entity", company_code="SECOND")
        WorkflowService.set_approval_policy(creator, enabled=True, threshold="700.00")
        second_context = AccessContext(identity_type="user", organisation_id=second.id,
                                       user_id=creator.user_id, full_access=True)
        assert not WorkflowService.approval_policy(second_context).get("enabled")
        with pytest.raises(PermissionError):
            WorkflowService.set_approval_policy(
                AccessContext(identity_type="user", organisation_id=creator.organisation_id,
                              user_id=creator.user_id, permissions=frozenset()),
                enabled=True, threshold="100.00")
        with pytest.raises(WorkflowError, match="greater than zero"):
            WorkflowService.set_approval_policy(creator, enabled=True, threshold="0")
        assert WorkflowService.approval_policy(creator)["threshold"] == "700.00"


def test_named_checker_required_even_if_workflow_rule_allows_self_approval(app):
    with app.app_context():
        creator = _owner()
        rule = WorkflowService.create_definition(
            creator, name="Old permissive rule", entity_type="external_item",
            review_required=False, approval_required=True, separate_approver=False)
        instance = WorkflowService.start(creator, entity_type="external_item",
                                         entity_id="old-rule", title="Old rule",
                                         amount="15.00", definition_id=rule.id)
        action = UserAction.query.filter_by(workflow_instance_id=instance.id,
                                            action_type="approve").one()
        with pytest.raises(WorkflowError, match="creator cannot approve"):
            WorkflowService.complete_action(creator, action.id, decision="approve")
        assert action.status == "open"
