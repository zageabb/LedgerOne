"""ERP-000 order acknowledgements, goods receipt and delivery-note service.

This is deliberately non-posting: accepting goods or issuing a delivery note
must never silently write ledger entries or supplier/customer invoices.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.core import new_id
from ledgerone.modules.commercial.models import CommercialDocument, CommercialDocumentLine
from ledgerone.modules.purchases.order_models import PurchaseOrder
from ledgerone.modules.sales.order_models import SalesOrder
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


_DOCUMENTS = {
    "po_ack": ("purchases.write", PurchaseOrder, {"approved", "sent"}, "POA"),
    "grn": ("purchases.write", PurchaseOrder, {"approved", "sent"}, "GRN"),
    "so_ack": ("sales.write", SalesOrder, {"confirmed"}, "SOA"),
    "delivery_note": ("sales.write", SalesOrder, {"confirmed"}, "DN"),
}
_FULFILMENT = {"grn", "delivery_note"}


def _qty(value):
    try:
        result = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid document quantity") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("Document quantity must be positive and finite")
    return result


class CommercialDocumentService:
    @staticmethod
    def list_for_order(context: AccessContext, *, document_type: str, order_id: str):
        permission, order_model, _, _ = _DOCUMENTS.get(document_type, (None, None, None, None))
        if not permission:
            raise ValueError("Unknown document type")
        read_permission = permission.replace(".write", ".read")
        if not context.can(read_permission):
            raise PermissionError(read_permission)
        order = db.session.get(order_model, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Order not found")
        return (CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id, document_type=document_type,
            order_id=order.id).order_by(CommercialDocument.revision.asc()).all())

    @staticmethod
    def create(context: AccessContext, *, document_type: str, order_id: str,
               document_date: date, lines: list[dict] | None = None,
               external_reference: str | None = None, metadata: dict | None = None):
        if document_type not in _DOCUMENTS:
            raise ValueError("Unknown document type")
        permission, order_model, acceptable, prefix = _DOCUMENTS[document_type]
        if not context.can(permission):
            raise PermissionError(permission)
        order = db.session.get(order_model, order_id)
        if not order or order.organisation_id != context.organisation_id:
            raise ValueError("Order not found")
        if order.status not in acceptable:
            raise ValueError(f"Order must be {', '.join(sorted(acceptable))} to create {document_type}")
        if not isinstance(document_date, date):
            raise ValueError("Document date is required")
        if not isinstance(metadata or {}, dict):
            raise ValueError("Document metadata must be an object")
        if len(external_reference or "") > 120:
            raise ValueError("External reference is too long")
        order_lines = {line.id: line for line in order.lines}
        if not order_lines:
            raise ValueError("Order has no lines")
        if lines is None:
            if document_type in _FULFILMENT:
                raise ValueError("Explicit quantities are required for goods receipt and delivery")
            lines = [{"order_line_id": row.id, "quantity": str(row.quantity)}
                     for row in order.lines]
        if not isinstance(lines, list) or not lines:
            raise ValueError("At least one document line is required")
        seen = set()
        quantities = {}
        for supplied in lines:
            if not isinstance(supplied, dict):
                raise ValueError("Invalid document line")
            line_id = supplied.get("order_line_id")
            if line_id not in order_lines or line_id in seen:
                raise ValueError("Document line must be a unique line belonging to this order")
            seen.add(line_id)
            quantity = _qty(supplied.get("quantity"))
            if quantity > _qty(order_lines[line_id].quantity):
                raise ValueError("Document quantity exceeds ordered quantity")
            quantities[line_id] = (quantity, supplied.get("expected_date"))

        # Source document and cumulative fulfilment are scoped to the same
        # company/order. This is a separate document chain, not a journal post.
        if document_type in _FULFILMENT:
            prior = (CommercialDocument.query.filter_by(
                organisation_id=context.organisation_id,
                order_id=order_id, document_type=document_type,
                status="issued").all())
            consumed = {}
            for previous in prior:
                for row in previous.lines:
                    consumed[row.order_line_id] = consumed.get(row.order_line_id, Decimal(0)) + row.quantity
            for line_id, (quantity, _) in quantities.items():
                if consumed.get(line_id, Decimal(0)) + quantity > order_lines[line_id].quantity:
                    raise ValueError("Cumulative receipt/delivery exceeds outstanding ordered quantity")

        last = (CommercialDocument.query.filter_by(
            organisation_id=context.organisation_id,
            document_type=document_type, order_id=order_id)
            .order_by(CommercialDocument.revision.desc()).first())
        revision = last.revision + 1 if last else 1
        number = f"{prefix}-{order.order_number}-{revision:03d}"
        if len(number) > 120:
            raise ValueError("Generated document number exceeds supported length")
        document = CommercialDocument(
            id=new_id(), organisation_id=context.organisation_id,
            document_type=document_type, order_id=order_id,
            document_number=number, revision=revision,
            document_date=document_date, status="issued",
            external_reference=(external_reference or "").strip() or None,
            metadata_json=metadata or {},
            issued_by_user_id=context.user_id)
        db.session.add(document)
        db.session.flush()
        for position, (line_id, (quantity, expected_date)) in enumerate(quantities.items(), 1):
            line = order_lines[line_id]
            if expected_date and not isinstance(expected_date, date):
                raise ValueError("Confirmed date must be a date")
            db.session.add(CommercialDocumentLine(
                document_id=document.id, order_line_id=line_id,
                line_number=position, description=line.description,
                quantity=quantity, unit_price=line.unit_price,
                expected_date=expected_date))
        record_audit_event(
            context, module_id="purchases" if document_type in {"po_ack", "grn"} else "sales",
            action=f"{document_type}_issued", entity_type="commercial_document",
            entity_id=document.id,
            detail={"document_number": number, "source_order_id": order_id,
                    "revision": revision, "line_count": len(quantities)})
        db.session.commit()
        return document

    @staticmethod
    def respond_to_po_ack(context: AccessContext, document_id: str, *,
                          response_status: str, confirmed_date: date | None = None,
                          supplier_reference: str | None = None):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        document = db.session.get(CommercialDocument, document_id)
        if (not document or document.organisation_id != context.organisation_id
                or document.document_type != "po_ack"):
            raise ValueError("Purchase order acknowledgement not found")
        if document.response_status is not None:
            raise ValueError("Acknowledgement response is already recorded")
        if response_status not in {"accepted", "partially_accepted", "rejected", "changes_requested"}:
            raise ValueError("Invalid supplier acknowledgement response")
        if len(supplier_reference or "") > 120:
            raise ValueError("Supplier reference is too long")
        document.response_status = response_status
        document.confirmed_date = confirmed_date
        document.external_reference = (supplier_reference or "").strip() or document.external_reference
        record_audit_event(
            context, module_id="purchases", action="po_ack_supplier_response",
            entity_type="commercial_document", entity_id=document.id,
            detail={"response_status": response_status,
                    "supplier_reference": document.external_reference,
                    "confirmed_date": str(confirmed_date) if confirmed_date else None})
        db.session.commit()
        return document
