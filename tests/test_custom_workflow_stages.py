"""Custom workflow routing, value bands, and tenant separation."""
import pytest
from decimal import Decimal

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
            maker, entity_type="purchase_bill", amount=Decimal("100.00")
        ) is None
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


def test_company_admin_allocates_multiple_workflow_roles_and_approval_checks_permissions(app):
    from ledgerone.services.workflow_roles import WorkflowRoleService

    with app.app_context():
        owner = _owner()
        member = _member(owner.organisation_id, "multi-role@example.test", role="member")
        membership = Membership.query.filter_by(
            organisation_id=owner.organisation_id, user_id=member.user_id).one()
        assert WorkflowRoleService.assign(owner, membership.id,
                                          ["finance", "purchasing", "finance"]) == [
                                              "finance", "purchasing"]
        assert WorkflowRoleService.assignments(owner)[member.user_id] == [
            "finance", "purchasing"]
        definition = WorkflowService.create_definition(
            owner, name="Finance review", entity_type="purchase_bill",
            custom_steps=[{"type": "approve", "role": "finance"}])
        workflow = WorkflowService.start(
            owner, entity_type="purchase_bill", entity_id="finance-role-test",
            title="Finance-controlled bill", amount="700", definition_id=definition.id)
        action = UserAction.query.filter_by(workflow_instance_id=workflow.id,
                                            action_type="approve").one()
        assert action in WorkflowService.open_actions(member)
        WorkflowService.complete_action(member, action.id, decision="approve")
        assert workflow.status == "ready_to_post"

        # Membership and workflow routing are independent of permissions.
        member_no_permission = AccessContext(
            identity_type="user", organisation_id=owner.organisation_id,
            user_id=member.user_id, permissions=frozenset({"workflows.read"}))
        another = WorkflowService.start(
            owner, entity_type="purchase_bill", entity_id="finance-role-denied",
            title="Finance approval denied", amount="700", definition_id=definition.id)
        action2 = UserAction.query.filter_by(workflow_instance_id=another.id,
                                             action_type="approve").one()
        with pytest.raises(PermissionError, match="workflows.approve"):
            WorkflowService.complete_action(member_no_permission, action2.id,
                                            decision="approve")

        # A different company does not inherit any of these routing roles.
        other_company = CompanyService.create(
            owner, name="Separate Company", company_code="SEPARATE")
        foreign_member = Membership(
            organisation_id=other_company.id, user_id=member.user_id,
            role="member", permissions=["workflows.read", "workflows.approve"],
            is_active=True)
        db.session.add(foreign_member)
        db.session.commit()
        foreign_ctx = AccessContext(
            identity_type="user", organisation_id=other_company.id,
            user_id=member.user_id,
            permissions=frozenset({"workflows.read", "workflows.approve"}))
        assert WorkflowRoleService.assignments(
            AccessContext(identity_type="user", organisation_id=other_company.id,
                          user_id=owner.user_id, full_access=True)).get(member.user_id) is None
        other_rule = WorkflowService.create_definition(
            AccessContext(identity_type="user", organisation_id=other_company.id,
                          user_id=owner.user_id, full_access=True),
            name="Separate finance approval", entity_type="payment",
            custom_steps=[{"type": "approve", "role": "finance"}])
        other_workflow = WorkflowService.start(
            AccessContext(identity_type="user", organisation_id=other_company.id,
                          user_id=owner.user_id, full_access=True),
            entity_type="payment", entity_id="other-company-payment",
            title="Other payment", amount="1200", definition_id=other_rule.id)
        foreign_action = UserAction.query.filter_by(
            workflow_instance_id=other_workflow.id, action_type="approve").one()
        assert foreign_action not in WorkflowService.open_actions(foreign_ctx)
        with pytest.raises(PermissionError, match="assigned"):
            WorkflowService.complete_action(foreign_ctx, foreign_action.id,
                                            decision="approve")

        membership.is_active = False
        db.session.commit()
        assert WorkflowRoleService.assignments(owner)[member.user_id] == [
            "finance", "purchasing"]
        assert action2 not in WorkflowService.open_actions(
            AccessContext(identity_type="user", organisation_id=owner.organisation_id,
                          user_id=member.user_id,
                          permissions=frozenset({"workflows.read"})))


def test_non_admin_cannot_allocate_roles_and_cross_company_assignment_is_denied(app):
    from ledgerone.services.workflow_roles import WorkflowRoleService

    with app.app_context():
        owner = _owner()
        member = _member(owner.organisation_id, "restricted@example.test", role="member")
        membership = Membership.query.filter_by(
            organisation_id=owner.organisation_id, user_id=member.user_id).one()
        with pytest.raises(PermissionError):
            WorkflowRoleService.assign(member, membership.id, ["finance"])
        with pytest.raises(ValueError, match="workflow role"):
            WorkflowRoleService.assign(owner, membership.id, ["bad role with spaces"])
        other_company = CompanyService.create(
            owner, name="Another Co", company_code="ANOTHER")
        other_owner = AccessContext(
            identity_type="user", organisation_id=other_company.id,
            user_id=owner.user_id, full_access=True)
        with pytest.raises(ValueError, match="company membership"):
            WorkflowRoleService.assign(other_owner, membership.id, ["finance"])


def test_revoked_named_assignee_cannot_approve_even_if_the_action_remains_open(app):
    with app.app_context():
        owner = _owner()
        named = _member(owner.organisation_id, "named-revoked@example.test")
        rule = WorkflowService.create_definition(
            owner, name="Named finance checker", entity_type="journal",
            custom_steps=[{"type": "approve", "user_id": named.user_id}])
        workflow = WorkflowService.start(
            owner, entity_type="journal", entity_id="named-revoked",
            title="Journal to approve", amount="500", definition_id=rule.id)
        action = UserAction.query.filter_by(
            workflow_instance_id=workflow.id, action_type="approve").one()
        assert action in WorkflowService.open_actions(named)
        membership = Membership.query.filter_by(
            organisation_id=owner.organisation_id, user_id=named.user_id).one()
        membership.is_active = False
        db.session.commit()
        with pytest.raises(PermissionError, match="assigned"):
            WorkflowService.complete_action(named, action.id, decision="approve")
        assert action.status == "open"
