from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    __table_args__ = (
        db.UniqueConstraint(
            "chain_scope", "chain_sequence", name="uq_audit_event_scope_sequence"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=True, index=True)
    actor_type = db.Column(db.String(40), nullable=False, index=True)
    actor_id = db.Column(db.String(120), nullable=True, index=True)
    module_id = db.Column(db.String(80), nullable=False, index=True)
    action = db.Column(db.String(120), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=True, index=True)
    entity_id = db.Column(db.String(120), nullable=True, index=True)
    detail = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    chain_scope = db.Column(db.String(80), nullable=False, index=True)
    chain_sequence = db.Column(db.Integer, nullable=False, index=True)
    previous_hash = db.Column(db.String(64), nullable=True)
    event_hash = db.Column(db.String(64), nullable=False, index=True)
    chain_version = db.Column(db.Integer, nullable=False, default=1)


class AuditChainHead(db.Model):
    __tablename__ = "audit_chain_heads"

    scope_key = db.Column(db.String(80), primary_key=True)
    organisation_id = db.Column(
        db.String(36), db.ForeignKey("organisations.id"), nullable=True, index=True
    )
    last_sequence = db.Column(db.Integer, nullable=False, default=0)
    last_hash = db.Column(db.String(64), nullable=True)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
