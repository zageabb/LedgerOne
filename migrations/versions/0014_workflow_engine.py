"""Add generic workflow engine, user actions and recurring transaction templates.

Revision ID: 0014_workflow_engine
Revises: 0013_ai_workspace_knowledge
Create Date: 2026-09-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_workflow_engine"
down_revision: Union[str, None] = "0013_ai_workspace_knowledge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_definitions_organisation_id", "workflow_definitions", ["organisation_id"], unique=False)
    op.create_index("ix_workflow_definitions_entity_type", "workflow_definitions", ["entity_type"], unique=False)
    op.create_index("ix_workflow_definitions_priority", "workflow_definitions", ["priority"], unique=False)
    op.create_index("ix_workflow_definitions_is_active", "workflow_definitions", ["is_active"], unique=False)

    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_definition_id", sa.String(length=36), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("source_module", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("originator_user_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["workflow_definition_id"], ["workflow_definitions.id"]),
        sa.ForeignKeyConstraint(["originator_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "entity_type", "entity_id", name="uq_workflow_instance_entity"),
    )
    op.create_index("ix_workflow_instances_organisation_id", "workflow_instances", ["organisation_id"], unique=False)
    op.create_index("ix_workflow_instances_workflow_definition_id", "workflow_instances", ["workflow_definition_id"], unique=False)
    op.create_index("ix_workflow_instances_entity_type", "workflow_instances", ["entity_type"], unique=False)
    op.create_index("ix_workflow_instances_entity_id", "workflow_instances", ["entity_id"], unique=False)
    op.create_index("ix_workflow_instances_source_module", "workflow_instances", ["source_module"], unique=False)
    op.create_index("ix_workflow_instances_status", "workflow_instances", ["status"], unique=False)
    op.create_index("ix_workflow_instances_originator_user_id", "workflow_instances", ["originator_user_id"], unique=False)

    op.create_table(
        "user_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_instance_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("instructions", sa.String(length=1000), nullable=True),
        sa.Column("assigned_user_id", sa.String(length=36), nullable=True),
        sa.Column("assigned_role", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("decision", sa.String(length=30), nullable=True),
        sa.Column("comments", sa.String(length=1000), nullable=True),
        sa.Column("completed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["workflow_instance_id"], ["workflow_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["completed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_actions_organisation_id", "user_actions", ["organisation_id"], unique=False)
    op.create_index("ix_user_actions_workflow_instance_id", "user_actions", ["workflow_instance_id"], unique=False)
    op.create_index("ix_user_actions_action_type", "user_actions", ["action_type"], unique=False)
    op.create_index("ix_user_actions_assigned_user_id", "user_actions", ["assigned_user_id"], unique=False)
    op.create_index("ix_user_actions_assigned_role", "user_actions", ["assigned_role"], unique=False)
    op.create_index("ix_user_actions_status", "user_actions", ["status"], unique=False)
    op.create_index("ix_user_actions_due_date", "user_actions", ["due_date"], unique=False)

    op.create_table(
        "transaction_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("amount_mode", sa.String(length=30), nullable=False),
        sa.Column("expected_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("tolerance", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("counter_account_id", sa.String(length=36), nullable=False),
        sa.Column("frequency", sa.String(length=30), nullable=False),
        sa.Column("next_run_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("workflow_definition_id", sa.String(length=36), nullable=True),
        sa.Column("posting_mode", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["bank_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["counter_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["workflow_definition_id"], ["workflow_definitions.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transaction_templates_organisation_id", "transaction_templates", ["organisation_id"], unique=False)
    op.create_index("ix_transaction_templates_transaction_type", "transaction_templates", ["transaction_type"], unique=False)
    op.create_index("ix_transaction_templates_amount_mode", "transaction_templates", ["amount_mode"], unique=False)
    op.create_index("ix_transaction_templates_frequency", "transaction_templates", ["frequency"], unique=False)
    op.create_index("ix_transaction_templates_next_run_date", "transaction_templates", ["next_run_date"], unique=False)
    op.create_index("ix_transaction_templates_is_active", "transaction_templates", ["is_active"], unique=False)

    op.create_table(
        "scheduled_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("expected_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("actual_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("counter_account_id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("workflow_instance_id", sa.String(length=36), nullable=True),
        sa.Column("journal_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["transaction_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bank_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["counter_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["workflow_instance_id"], ["workflow_instances.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "scheduled_date", name="uq_scheduled_transaction_template_date"),
        sa.UniqueConstraint("workflow_instance_id"),
        sa.UniqueConstraint("journal_id"),
    )
    op.create_index("ix_scheduled_transactions_organisation_id", "scheduled_transactions", ["organisation_id"], unique=False)
    op.create_index("ix_scheduled_transactions_template_id", "scheduled_transactions", ["template_id"], unique=False)
    op.create_index("ix_scheduled_transactions_scheduled_date", "scheduled_transactions", ["scheduled_date"], unique=False)
    op.create_index("ix_scheduled_transactions_transaction_type", "scheduled_transactions", ["transaction_type"], unique=False)
    op.create_index("ix_scheduled_transactions_status", "scheduled_transactions", ["status"], unique=False)


def downgrade():
    op.drop_index("ix_scheduled_transactions_status", table_name="scheduled_transactions")
    op.drop_index("ix_scheduled_transactions_transaction_type", table_name="scheduled_transactions")
    op.drop_index("ix_scheduled_transactions_scheduled_date", table_name="scheduled_transactions")
    op.drop_index("ix_scheduled_transactions_template_id", table_name="scheduled_transactions")
    op.drop_index("ix_scheduled_transactions_organisation_id", table_name="scheduled_transactions")
    op.drop_table("scheduled_transactions")

    op.drop_index("ix_transaction_templates_is_active", table_name="transaction_templates")
    op.drop_index("ix_transaction_templates_next_run_date", table_name="transaction_templates")
    op.drop_index("ix_transaction_templates_frequency", table_name="transaction_templates")
    op.drop_index("ix_transaction_templates_amount_mode", table_name="transaction_templates")
    op.drop_index("ix_transaction_templates_transaction_type", table_name="transaction_templates")
    op.drop_index("ix_transaction_templates_organisation_id", table_name="transaction_templates")
    op.drop_table("transaction_templates")

    op.drop_index("ix_user_actions_due_date", table_name="user_actions")
    op.drop_index("ix_user_actions_status", table_name="user_actions")
    op.drop_index("ix_user_actions_assigned_role", table_name="user_actions")
    op.drop_index("ix_user_actions_assigned_user_id", table_name="user_actions")
    op.drop_index("ix_user_actions_action_type", table_name="user_actions")
    op.drop_index("ix_user_actions_workflow_instance_id", table_name="user_actions")
    op.drop_index("ix_user_actions_organisation_id", table_name="user_actions")
    op.drop_table("user_actions")

    op.drop_index("ix_workflow_instances_originator_user_id", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_status", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_source_module", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_entity_id", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_entity_type", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_workflow_definition_id", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_organisation_id", table_name="workflow_instances")
    op.drop_table("workflow_instances")

    op.drop_index("ix_workflow_definitions_is_active", table_name="workflow_definitions")
    op.drop_index("ix_workflow_definitions_priority", table_name="workflow_definitions")
    op.drop_index("ix_workflow_definitions_entity_type", table_name="workflow_definitions")
    op.drop_index("ix_workflow_definitions_organisation_id", table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
