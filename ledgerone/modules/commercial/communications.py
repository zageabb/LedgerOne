"""Purpose-coded supplier/customer contacts and auditable unsent document drafts."""
import re

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.modules.commercial.models import (
    CommercialContactRoute, CommercialDocument, CommercialMessageDraft,
)
from ledgerone.modules.purchases.models import Supplier
from ledgerone.modules.sales.models import Customer
from ledgerone.services.audit import record_audit_event

_EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
_PURPOSES = {"ORDERS", "ACCOUNTS", "LOGISTICS", "QUOTES", "RETURNS"}
_CONTACT_MODELS = {"supplier": Supplier, "customer": Customer}
_DOC_PARTIES = {
    "po_ack": ("supplier", "ORDERS"),
    "grn": ("supplier", "LOGISTICS"),
    "so_ack": ("customer", "ORDERS"),
    "delivery_note": ("customer", "LOGISTICS"),
}


class CommercialCommunicationService:
    @staticmethod
    def add_route(context, *, party_type: str, party_id: str, purpose: str,
                  email: str, contact_name: str | None = None):
        if party_type not in _CONTACT_MODELS:
            raise ValueError("Invalid contact party type")
        permission = "purchases.write" if party_type == "supplier" else "sales.write"
        if not context.can(permission):
            raise PermissionError(permission)
        party = db.session.get(_CONTACT_MODELS[party_type], party_id)
        if not party or party.organisation_id != context.organisation_id:
            raise ValueError("Contact party not found in company")
        purpose = (purpose or "").strip().upper()
        email = (email or "").strip().lower()
        if purpose not in _PURPOSES:
            raise ValueError("Invalid contact purpose")
        if len(email) > 255 or not _EMAIL.fullmatch(email):
            raise ValueError("Valid email address required")
        if len(contact_name or "") > 160:
            raise ValueError("Contact name is too long")
        duplicate = CommercialContactRoute.query.filter_by(
            organisation_id=context.organisation_id, party_type=party_type,
            party_id=party_id, purpose=purpose, email=email).first()
        if duplicate:
            raise ValueError("Contact route already exists")
        record = CommercialContactRoute(
            id=new_id(), organisation_id=context.organisation_id,
            party_type=party_type, party_id=party_id,
            purpose=purpose, email=email, contact_name=(contact_name or "").strip() or None,
            is_active=True)
        db.session.add(record)
        record_audit_event(
            context, module_id="purchases" if party_type == "supplier" else "sales",
            action="contact_route_created", entity_type="commercial_contact_route",
            entity_id=record.id,
            detail={"party_id": party_id, "party_type": party_type,
                    "purpose": purpose, "email": email})
        db.session.commit()
        return record

    @staticmethod
    def routes(context, *, party_type: str, party_id: str, purpose: str | None = None):
        if party_type not in _CONTACT_MODELS:
            raise ValueError("Invalid party type")
        permission = "purchases.read" if party_type == "supplier" else "sales.read"
        if not context.can(permission):
            raise PermissionError(permission)
        party = db.session.get(_CONTACT_MODELS[party_type], party_id)
        if not party or party.organisation_id != context.organisation_id:
            raise ValueError("Contact party not found in company")
        query = CommercialContactRoute.query.filter_by(
            organisation_id=context.organisation_id, party_type=party_type,
            party_id=party_id, is_active=True)
        if purpose:
            query = query.filter_by(purpose=purpose.strip().upper())
        return query.order_by(CommercialContactRoute.email.asc()).all()

    @staticmethod
    def draft_document_email(context, *, document_id: str,
                             idempotency_key: str, subject: str | None = None,
                             body: str | None = None):
        document = db.session.get(CommercialDocument, document_id)
        if not document or document.organisation_id != context.organisation_id:
            raise ValueError("Document not found in company")
        party_type, purpose = _DOC_PARTIES[document.document_type]
        write_permission = "purchases.write" if party_type == "supplier" else "sales.write"
        if not context.can(write_permission):
            raise PermissionError(write_permission)
        if not context.user_id:
            raise PermissionError("Named user required to prepare outbound communication")
        if document.status != "issued":
            raise ValueError("Only issued document revisions can be emailed")
        key = (idempotency_key or "").strip()
        if not 1 <= len(key) <= 120:
            raise ValueError("An idempotency key is required")
        existing = CommercialMessageDraft.query.filter_by(
            organisation_id=context.organisation_id, idempotency_key=key).first()
        if existing:
            if existing.document_id != document_id:
                raise ValueError("Idempotency key is already used for another document")
            return existing
        from ledgerone.modules.purchases.order_models import PurchaseOrder
        from ledgerone.modules.sales.order_models import SalesOrder
        model = PurchaseOrder if party_type == "supplier" else SalesOrder
        order = db.session.get(model, document.order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Source order not found in company")
        party_id = order.supplier_id if party_type == "supplier" else order.customer_id
        contacts = CommercialCommunicationService.routes(
            context, party_type=party_type, party_id=party_id, purpose=purpose)
        if not contacts:
            raise ValueError(f"No configured {purpose} email contact for this {party_type}")
        title = (subject or f"{document.document_type.upper()} {document.document_number}").strip()
        message = (body or f"Please find details of {document.document_number}.").strip()
        if not title or len(title) > 255 or not message or len(message) > 20000:
            raise ValueError("Invalid message subject or body")
        row = CommercialMessageDraft(
            id=new_id(), organisation_id=context.organisation_id,
            document_id=document.id, purpose=purpose,
            recipients_json=[c.email for c in contacts], subject=title,
            body=message, status="draft", idempotency_key=key,
            created_by_user_id=context.user_id)
        db.session.add(row)
        record_audit_event(
            context, module_id="purchases" if party_type == "supplier" else "sales",
            action="commercial_email_drafted",
            entity_type="commercial_message_draft", entity_id=row.id,
            detail={"document_id": document.id, "purpose": purpose,
                    "recipient_count": len(contacts)})
        db.session.commit()
        return row
