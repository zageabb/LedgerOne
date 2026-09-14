from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app
from werkzeug.utils import secure_filename

from ledgerone.extensions import db
from ledgerone.models.ledger import Journal
from ledgerone.modules.documents.models import SourceDocument
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class DocumentError(ValueError):
    pass


class DocumentService:
    TARGETS = {
        "journal": "ledger",
        "sales_invoice": "sales",
        "purchase_bill": "purchases",
        "bank_transaction": "banking",
        "expense_claim": "expense_claims",
    }

    @staticmethod
    def _target_module(context: AccessContext, entity_type: str, entity_id: str) -> str:
        entity_type = (entity_type or "").strip().lower()
        entity_id = (entity_id or "").strip()
        module_id = DocumentService.TARGETS.get(entity_type)
        if not module_id or not entity_id:
            raise DocumentError("Unsupported or missing source-document target")

        if entity_type == "journal":
            row = db.session.get(Journal, entity_id)
            valid = bool(row and row.organisation_id == context.organisation_id)
        elif entity_type == "sales_invoice":
            from ledgerone.modules.sales.models import SalesInvoice
            row = db.session.get(SalesInvoice, entity_id)
            valid = bool(row and row.organisation_id == context.organisation_id)
        elif entity_type == "purchase_bill":
            from ledgerone.modules.purchases.models import PurchaseBill
            row = db.session.get(PurchaseBill, entity_id)
            valid = bool(row and row.organisation_id == context.organisation_id)
        elif entity_type == "expense_claim":
            from ledgerone.modules.expense_claims.models import ExpenseClaim
            row = db.session.get(ExpenseClaim, entity_id)
            valid = bool(row and row.organisation_id == context.organisation_id)
        else:
            from ledgerone.modules.banking.models import BankAccount, BankTransaction
            row = db.session.get(BankTransaction, entity_id)
            valid = bool(
                row
                and db.session.get(BankAccount, row.bank_account_id)
                and row.bank_account.organisation_id == context.organisation_id
            )
        if not valid:
            raise DocumentError("Source-document target was not found in this organisation")
        return module_id

    @staticmethod
    def list_documents(
        context: AccessContext,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        module_id: str | None = None,
        limit: int = 200,
    ):
        if not context.can("documents.read"):
            raise PermissionError("documents.read")
        query = SourceDocument.query.filter_by(organisation_id=context.organisation_id)
        if entity_type:
            query = query.filter(SourceDocument.entity_type == entity_type)
        if entity_id:
            query = query.filter(SourceDocument.entity_id == entity_id)
        if module_id:
            query = query.filter(SourceDocument.module_id == module_id)
        return (
            query.order_by(SourceDocument.created_at.desc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )

    @staticmethod
    def create_reference(
        context: AccessContext,
        *,
        entity_type: str,
        entity_id: str,
        reference_url: str,
        title: str | None = None,
    ):
        if not context.can("documents.write"):
            raise PermissionError("documents.write")
        module_id = DocumentService._target_module(context, entity_type, entity_id)
        reference_url = (reference_url or "").strip()
        parsed = urlparse(reference_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DocumentError("Reference URL must be a valid http:// or https:// address")
        row = SourceDocument(
            organisation_id=context.organisation_id,
            module_id=module_id,
            entity_type=entity_type.strip().lower(),
            entity_id=entity_id.strip(),
            kind="reference",
            title=(title or "").strip() or parsed.netloc,
            reference_url=reference_url,
            uploaded_by_user_id=context.user_id,
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="documents",
            action="source_reference_added",
            entity_type="source_document",
            entity_id=row.id,
            detail={
                "target_type": row.entity_type,
                "target_id": row.entity_id,
                "reference_url": row.reference_url,
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def create_file(
        context: AccessContext,
        *,
        entity_type: str,
        entity_id: str,
        upload,
        title: str | None = None,
    ):
        if not context.can("documents.write"):
            raise PermissionError("documents.write")
        module_id = DocumentService._target_module(context, entity_type, entity_id)
        if upload is None or not getattr(upload, "filename", None):
            raise DocumentError("A file is required")
        filename = secure_filename(upload.filename)
        if not filename:
            raise DocumentError("The uploaded filename is not valid")
        max_bytes = int(current_app.config.get("DOCUMENT_MAX_BYTES", 25 * 1024 * 1024))
        data = upload.stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise DocumentError(f"Document exceeds the {max_bytes // (1024 * 1024)} MB limit")
        if not data:
            raise DocumentError("The uploaded file is empty")

        row = SourceDocument(
            organisation_id=context.organisation_id,
            module_id=module_id,
            entity_type=entity_type.strip().lower(),
            entity_id=entity_id.strip(),
            kind="file",
            title=(title or "").strip() or filename,
            original_filename=filename,
            content_type=(getattr(upload, "mimetype", None) or "application/octet-stream")[:255],
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            uploaded_by_user_id=context.user_id,
        )
        db.session.add(row)
        db.session.flush()

        root = Path(current_app.config["DOCUMENT_STORAGE_DIR"]).resolve()
        relative = Path(str(context.organisation_id)) / row.id / filename
        destination = (root / relative).resolve()
        if root != destination and root not in destination.parents:
            raise DocumentError("Invalid document storage path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        row.storage_key = relative.as_posix()

        try:
            record_audit_event(
                context,
                module_id="documents",
                action="source_document_uploaded",
                entity_type="source_document",
                entity_id=row.id,
                detail={
                    "target_type": row.entity_type,
                    "target_id": row.entity_id,
                    "filename": filename,
                    "size_bytes": len(data),
                    "sha256": row.sha256,
                },
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            destination.unlink(missing_ok=True)
            raise
        return row

    @staticmethod
    def get_document(context: AccessContext, document_id: str):
        if not context.can("documents.read"):
            raise PermissionError("documents.read")
        row = db.session.get(SourceDocument, document_id)
        if not row or row.organisation_id != context.organisation_id:
            raise DocumentError("Source document not found")
        return row

    @staticmethod
    def file_path(context: AccessContext, document_id: str) -> Path:
        row = DocumentService.get_document(context, document_id)
        if row.kind != "file" or not row.storage_key:
            raise DocumentError("This source document is not a stored file")
        root = Path(current_app.config["DOCUMENT_STORAGE_DIR"]).resolve()
        path = (root / row.storage_key).resolve()
        if root != path and root not in path.parents:
            raise DocumentError("Invalid document storage path")
        if not path.is_file():
            raise DocumentError("Stored source document is missing")
        return path

    @staticmethod
    def serialise(row: SourceDocument):
        return {
            "id": row.id,
            "module_id": row.module_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "kind": row.kind,
            "title": row.title,
            "original_filename": row.original_filename,
            "reference_url": row.reference_url,
            "content_type": row.content_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "created_at": row.created_at.isoformat(),
        }
