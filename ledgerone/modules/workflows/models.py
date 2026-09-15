from __future__ import annotations

from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class WorkflowDefinition(db.Model):
    __tablename__ = "workflow_definitions"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    entity_type = db.Column(db.String(80), nullable=False, default="scheduled_transaction", index=True)
    priority = db.Column(db.Integer, nullable=False, default=100, index=True)
    rules_json = db.Column(db.JSON, nullable=False, default=dict)
    steps_json = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class WorkflowInstance(db.Model):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        db.UniqueConstraint(
            "organisation_id", "entity_type", "entity_id", name="uq_workflow_instance_entity"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    workflow_definition_id = db.Column(db.String(36), db.ForeignKey("workflow_definitions.id"), nullable=True, index=True)
    entity_type = db.Column(db.String(80), nullable=False, index=True)
    entity_id = db.Column(db.String(36), nullable=False, index=True)
    source_module = db.Column(db.String(80), nullable=False, default="workflows", index=True)
    title = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    status = db.Column(db.String(40), nullable=False, default="draft", index=True)
    current_step_index = db.Column(db.Integer, nullable=False, default=0)
    originator_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True, index=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    definition = db.relationship("WorkflowDefinition")
    actions = db.relationship(
        "UserAction",
        back_populates="workflow_instance",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class UserAction(db.Model):
    __tablename__ = "user_actions"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    workflow_instance_id = db.Column(db.String(36), db.ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type = db.Column(db.String(40), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    instructions = db.Column(db.String(1000), nullable=True)
    assigned_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True, index=True)
    assigned_role = db.Column(db.String(40), nullable=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    due_date = db.Column(db.Date, nullable=True, index=True)
    decision = db.Column(db.String(30), nullable=True)
    comments = db.Column(db.String(1000), nullable=True)
    completed_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    workflow_instance = db.relationship("WorkflowInstance", back_populates="actions")
    assigned_user = db.relationship("User", foreign_keys=[assigned_user_id])
    completed_by = db.relationship("User", foreign_keys=[completed_by_user_id])


class TransactionTemplate(db.Model):
    __tablename__ = "transaction_templates"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    transaction_type = db.Column(db.String(30), nullable=False, index=True)
    amount_mode = db.Column(db.String(30), nullable=False, default="expected", index=True)
    expected_amount = db.Column(db.Numeric(18, 2), nullable=True)
    tolerance = db.Column(db.Numeric(18, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    bank_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    counter_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    frequency = db.Column(db.String(30), nullable=False, index=True)
    next_run_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    workflow_definition_id = db.Column(db.String(36), db.ForeignKey("workflow_definitions.id"), nullable=True)
    posting_mode = db.Column(db.String(20), nullable=False, default="manual")
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    bank_account = db.relationship("Account", foreign_keys=[bank_account_id])
    counter_account = db.relationship("Account", foreign_keys=[counter_account_id])
    workflow_definition = db.relationship("WorkflowDefinition")
    generated_items = db.relationship(
        "ScheduledTransaction", back_populates="template", cascade="all, delete-orphan"
    )


class ScheduledTransaction(db.Model):
    __tablename__ = "scheduled_transactions"
    __table_args__ = (
        db.UniqueConstraint("template_id", "scheduled_date", name="uq_scheduled_transaction_template_date"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    template_id = db.Column(db.String(36), db.ForeignKey("transaction_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    transaction_type = db.Column(db.String(30), nullable=False, index=True)
    description = db.Column(db.String(500), nullable=False)
    expected_amount = db.Column(db.Numeric(18, 2), nullable=True)
    actual_amount = db.Column(db.Numeric(18, 2), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="GBP")
    bank_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    counter_account_id = db.Column(db.String(36), db.ForeignKey("accounts.id"), nullable=False)
    reference = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="generated", index=True)
    workflow_instance_id = db.Column(db.String(36), db.ForeignKey("workflow_instances.id"), nullable=True, unique=True)
    journal_id = db.Column(db.String(36), db.ForeignKey("journals.id"), nullable=True, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    template = db.relationship("TransactionTemplate", back_populates="generated_items")
    bank_account = db.relationship("Account", foreign_keys=[bank_account_id])
    counter_account = db.relationship("Account", foreign_keys=[counter_account_id])
    workflow_instance = db.relationship("WorkflowInstance")
    journal = db.relationship("Journal")
