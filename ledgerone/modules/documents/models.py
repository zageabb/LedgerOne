from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class SourceDocument(db.Model):
    __tablename__ = "source_documents"
    __table_args__ = (
        db.Index(
            "ix_source_documents_entity",
            "organisation_id",
            "entity_type",
            "entity_id",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(
        db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True
    )
    module_id = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=False, index=True)
    entity_id = db.Column(db.String(120), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, default="file", index=True)
    title = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=True)
    storage_key = db.Column(db.String(500), nullable=True, unique=True)
    reference_url = db.Column(db.String(1000), nullable=True)
    content_type = db.Column(db.String(255), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    sha256 = db.Column(db.String(64), nullable=True, index=True)
    uploaded_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
