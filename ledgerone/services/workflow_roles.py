"""Manage company-local workflow routing roles.

These labels route review/approval work and do not grant application permissions.
The primary Membership.role remains separate.
"""
import re

from ledgerone.extensions import db
from ledgerone.models.core import Membership, User
from ledgerone.modules.workflows.models import WorkflowRoleAssignment
from ledgerone.services.audit import record_audit_event


class WorkflowRoleService:
    SUGGESTED = ("finance", "finance_manager", "purchasing", "sales",
                 "payment_approver", "director", "operations")

    @staticmethod
    def assignments(context):
        if not context.can("settings.read"):
            raise PermissionError("settings.read")
        rows = WorkflowRoleAssignment.query.filter_by(
            organisation_id=context.organisation_id).all()
        result = {}
        for row in rows:
            result.setdefault(row.user_id, []).append(row.role)
        return {user_id: sorted(roles) for user_id, roles in result.items()}

    @staticmethod
    def assign(context, membership_id: str, roles: list[str]):
        if not context.can("settings.manage") or not context.user_id:
            raise PermissionError("settings.manage")
        membership = db.session.get(Membership, membership_id)
        if (not membership or membership.organisation_id != context.organisation_id
                or not membership.is_active):
            raise ValueError("Active company membership not found")
        user = db.session.get(User, membership.user_id)
        if not user or not user.is_active:
            raise ValueError("User is not active")
        clean = sorted({str(item).strip().lower() for item in roles if str(item).strip()})
        if len(clean) > 12:
            raise ValueError("Maximum of 12 workflow roles per person")
        if any(not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", role) for role in clean):
            raise ValueError("Each workflow role must be 2-40 lowercase letters, digits, _ or -")
        old = WorkflowRoleAssignment.query.filter_by(
            organisation_id=context.organisation_id, user_id=membership.user_id).all()
        before = sorted(row.role for row in old)
        for row in old:
            db.session.delete(row)
        db.session.flush()
        for role in clean:
            db.session.add(WorkflowRoleAssignment(
                organisation_id=context.organisation_id,
                user_id=membership.user_id, role=role))
        record_audit_event(context, module_id="workflows",
                           action="workflow_roles_updated",
                           entity_type="membership", entity_id=membership.id,
                           detail={"user_id": membership.user_id,
                                   "before": before, "after": clean})
        db.session.commit()
        return clean
