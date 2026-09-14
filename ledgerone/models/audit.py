from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

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
