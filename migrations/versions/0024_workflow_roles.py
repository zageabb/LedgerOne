"""Add company-specific workflow role allocation.

Revision ID: 0024_workflow_roles
Revises: 0023_multi_company
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_workflow_roles"
down_revision = "0023_multi_company"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_role_assignments",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("organisation_id", sa.String(36), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "user_id", "role", name="uq_workflow_role_org_user_role"),
    )
    op.create_index("ix_workflow_role_assignments_organisation_id", "workflow_role_assignments", ["organisation_id"])
    op.create_index("ix_workflow_role_assignments_user_id", "workflow_role_assignments", ["user_id"])
    op.create_index("ix_workflow_role_assignments_role", "workflow_role_assignments", ["role"])


def downgrade():
    op.drop_index("ix_workflow_role_assignments_role", table_name="workflow_role_assignments")
    op.drop_index("ix_workflow_role_assignments_user_id", table_name="workflow_role_assignments")
    op.drop_index("ix_workflow_role_assignments_organisation_id", table_name="workflow_role_assignments")
    op.drop_table("workflow_role_assignments")
