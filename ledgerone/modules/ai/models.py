from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class AIConversation(db.Model):
    __tablename__ = "ai_conversations"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    owner_identity_type = db.Column(db.String(32), nullable=False, default="user")
    owner_identity_id = db.Column(db.String(36), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False, default="New conversation")
    archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class AIInteraction(db.Model):
    __tablename__ = "ai_interactions"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    conversation_id = db.Column(db.String(36), db.ForeignKey("ai_conversations.id"), nullable=True, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True, index=True)
    requester_type = db.Column(db.String(32), nullable=True)
    requester_id = db.Column(db.String(36), nullable=True, index=True)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=True)
    model = db.Column(db.String(255), nullable=True)
    tool_log = db.Column(db.JSON, nullable=False, default=list)
    knowledge_log = db.Column(db.JSON, nullable=False, default=list)
    success = db.Column(db.Boolean, nullable=False, default=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class KnowledgeSource(db.Model):
    __tablename__ = "ai_knowledge_sources"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=True)
    media_type = db.Column(db.String(120), nullable=True)
    content = db.Column(db.Text, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="ready", index=True)
    uploaded_by_type = db.Column(db.String(32), nullable=True)
    uploaded_by_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    chunks = db.relationship(
        "KnowledgeChunk",
        backref="source",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="KnowledgeChunk.chunk_index",
    )


class KnowledgeChunk(db.Model):
    __tablename__ = "ai_knowledge_chunks"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    source_id = db.Column(db.String(36), db.ForeignKey("ai_knowledge_sources.id"), nullable=False, index=True)
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
