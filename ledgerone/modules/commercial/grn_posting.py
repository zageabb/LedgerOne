"""Atomic, gated stock-receipt journal service.

Deliberately not exposed through a web/API action or enabled in company
Settings. Activation requires completed supplier-invoice GRNI clearing.
"""
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import Setting, new_id
from ledgerone.modules.commercial.models import CommercialAccountingEvent, CommercialDocument
from ledgerone.modules.commercial.grn_accounting import GRNAccountingPreviewService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.inventory_accounting import InventoryAccountingConfiguration
from ledgerone.services.ledger import LedgerService


class GRNPostingService:
    EVENT_TYPE = "grn_inventory_accrual"

    @staticmethod
    def linked_event(context, grn_id):
        if not context.can("purchases.read"):
            raise PermissionError("purchases.read")
        document = db.session.get(CommercialDocument, grn_id)
        if not document or document.organisation_id != context.organisation_id or document.document_type != "grn":
            raise ValueError("GRN not found")
        return CommercialAccountingEvent.query.filter_by(
            organisation_id=context.organisation_id, document_id=grn_id,
            event_type=GRNPostingService.EVENT_TYPE).first()

    @staticmethod
    def post(context, *, grn_id):
        if not context.can("purchases.write"):
            raise PermissionError("purchases.write")
        # There is no external pathway to activate this pending the
        # supplier-invoice GRNI-clearing integration and accounting acceptance.
        setting = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=InventoryAccountingConfiguration.SCOPE,
            key=InventoryAccountingConfiguration.KEY).first()
        saved = dict(setting.value or {}) if setting else {}
        if (not saved.get("receipt_posting_enabled")
                or not saved.get("grni_bill_clearing_certified")):
            raise ValueError("GRN posting is disabled until supplier invoice GRNI clearing is certified")
        # Lock GRN to serialize attempted posts on PostgreSQL; uniqueness
        # constraints on CommercialAccountingEvent prevent duplicate commits.
        document = (CommercialDocument.query.filter_by(
            id=grn_id, organisation_id=context.organisation_id,
            document_type="grn").with_for_update().first())
        if not document:
            raise ValueError("GRN not found")
        if CommercialAccountingEvent.query.filter_by(
                organisation_id=context.organisation_id,
                document_id=grn_id, event_type=GRNPostingService.EVENT_TYPE).first():
            raise ValueError("This GRN is already linked to an accounting journal")
        preview = GRNAccountingPreviewService.preview(context, grn_id=grn_id)
        if preview["issues"] or not preview["lines"]:
            raise ValueError("GRN accrual prerequisites failed: " + ", ".join(preview["issues"]))
        value = Decimal(preview["stock_cost_value"])
        try:
            journal = LedgerService.post_journal(
                context, journal_date=document.document_date,
                description=f"Inventory receipt {document.document_number}",
                reference=document.document_number, source_module="purchases",
                source_reference=document.id,
                lines=[
                    {"account_id": row["account_id"], "debit": row["debit"],
                     "credit": row["credit"], "description": document.document_number,
                     "currency": preview["currency"]}
                    for row in preview["lines"]
                ], commit=False,
                metadata={"commercial_document_id": document.id,
                          "event_type": GRNPostingService.EVENT_TYPE,
                          "valuation_basis": "po_unit_price"},
            )
            event = CommercialAccountingEvent(
                id=new_id(), organisation_id=context.organisation_id,
                document_id=document.id, event_type=GRNPostingService.EVENT_TYPE,
                journal_id=journal.id, posted_value=value,
                metadata_json={"grn_number": document.document_number,
                               "stock_lines": preview["breakdown"]})
            db.session.add(event)
            db.session.flush()
            record_audit_event(
                context, module_id="purchases", action="grn_inventory_accrual_posted",
                entity_type="commercial_accounting_event", entity_id=event.id,
                detail={"grn_id": document.id, "journal_id": journal.id,
                        "value": str(value)})
            db.session.commit()
            return event
        except Exception:
            db.session.rollback()
            raise
