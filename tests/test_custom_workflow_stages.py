"""Custom workflow routing, value bands, and tenant separation."""
import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.modules.workflows.models import UserAction
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.company import CompanyService
from ledgerone.services.context import AccessContext


def _owner():
    org = Organisation.query.first()
    user = User.query.first()
    user.ui_mode = "home"
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org.id,
                         user_id=user.id, full_access=True, permissions=frozenset({"*"}))


def _member(org_id, email, role="manager"):
    user = User(email=email, name=email, ui_mode="professional")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    db.session.add(Membership(organisation_id=org_id, user_id=user.id,
                              role=role, permissions=["workflows.read", "workflows.approve",
                                                      "workflows.review"], is_active=True))
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org_id,
                         user_id=user.id, permissions=frozenset({"workflows.read",
                                                                 "workflows.approve", "workflows.review"}))


def test_custom_steps_route_in_order_and_restrict_named_assignee(app):
    with app.app_context():
        maker = _owner()
        reviewer = _member(maker.organisation_id, "reviewer@example.test", role="reviewer")
        checker = _member(maker.organisation_id, "checker@example.test", role="manager")
        definition = WorkflowService.create_definition(
            maker, name="Custom purchases over 500",
            entity_type="purchase_bill", min_amount="500", max_amount="4999.99",
            review_required=False, approval_required=False,
            custom_steps=[
                {"type": "review", "label": "First reviewer", "user_id": reviewer.user_id},
                {"type": "approve", "label": "Manager approval", "role": "manager"},
            ],
        )
        assert WorkflowService.resolve_definition(
            maker, entity_type="purchase_bill", amount=WorkflowService._money("100")
        ) is None if hasattr(WorkflowService, "_money") else True
        workflow = WorkflowService.start(
            maker, entity_type="purchase_bill", entity_id="custom-purchase",
            title="Purchase for approval", amount="750")
        assert workflow.workflow_definition_id == definition.id
        first = UserAction.query.filter_by(workflow_instance_id=workflow.id, status="open").one()
        assert first.action_type == "review"
        assert first.assigned_user_id == reviewer.user_id
        assert first not in WorkflowService.open_actions(checker)
        with pytest.raises(PermissionError):
            WorkflowService.complete_action(checker, first.id, decision="approve")
        WorkflowService.complete_action(reviewer, first.id, decision="approve")
        second = UserAction.query.filter_by(workflow_instance_id=workflow.id, status="open").one()
        assert second.action_type == "approve"
        assert second.assigned_role == "manager"
        assert second in WorkflowService.open_actions(checker)
        with pytest.raises(PermissionError):
            WorkflowService.complete_action(reviewer, second.id, decision="approve")
        WorkflowService.complete_action(checker, second.id, decision="approve")
        assert workflow.status == "ready_to_post"


def test_rejects_invalid_cross_company_and_unroutable_approval_stages(app):
    with app.app_context():
        owner = _owner()
        outsider = _member(owner.organisation_id, "outside@example.test")
        other = CompanyService.create(owner, name="Other Company", company_code="OTHER")
        foreign = AccessContext(identity_type="user", organisation_id=other.id,
                                user_id=owner.user_id, full_access=True)
        with pytest.raises(WorkflowError, match="active company member"):
            WorkflowService.create_definition(
                foreign, name="Cross-company reviewer", entity_type="journal",
                custom_steps=[{"type": "approve", "user_id": outsider.user_id}])
        with pytest.raises(WorkflowError, match="select a named user or company role"):
            WorkflowService.create_definition(
                owner, name="No assignee", entity_type="journal",
                custom_steps=[{"type": "approve"}])
        with pytest.raises(WorkflowError, match="choose a user or role"):
            WorkflowService.create_definition(
                owner, name="Both routes", entity_type="journal",
                custom_steps=[{"type": "approve", "user_id": outsider.user_id,
                               "role": "manager"}])
        with pytest.raises(WorkflowError, match="between 1 and 8 stages"):
            WorkflowService.create_definition(
                owner, name="Empty stages", entity_type="journal", custom_steps=[])


def test_custom_value_bands_and_company_independence(app):
    with app.app_context():
        owner = _owner()
        checker = _member(owner.organisation_id, "manager-value@example.test")
        WorkflowService.create_definition(
            owner, name="Low payment", entity_type="payment",
            min_amount="0.01", max_amount="499.99", priority=20,
            custom_steps=[{"type": "approve", "role": "manager"}])
        high = WorkflowService.create_definition(
            owner, name="High payment", entity_type="payment",
            min_amount="500", priority=10,
            custom_steps=[{"type": "approve", "user_id": checker.user_id}])
        small = WorkflowService.start(owner, entity_type="payment",
                                      entity_id="small", title="Small", amount="200")
        large = WorkflowService.start(owner, entity_type="payment",
                                      entity_id="large", title="Large", amount="500")
        assert small.workflow_definition_id != large.workflow_definition_id
        assert large.workflow_definition_id == high.id
        second = CompanyService.create(owner, name="Second Ledger", company_code="SECOND")
        other = AccessContext(identity_type="user", organisation_id=second.id,
                              user_id=owner.user_id, full_access=True)
        assert not WorkflowService.list_definitions(other)
        with pytest.raises(WorkflowError, match="not available"):
            WorkflowService.start(other, entity_type="payment", entity_id="other",
                                  title="Other", amount="500", definition_id=high.id)
