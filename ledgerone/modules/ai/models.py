from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class AIInteraction(db.Model):
    __tablename__ = "ai_interactions"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True, index=True)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=True)
    model = db.Column(db.String(255), nullable=True)
    tool_log = db.Column(db.JSON, nullable=False, default=list)
    success = db.Column(db.Boolean, nullable=False, default=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
