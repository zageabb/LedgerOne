from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, or_

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import ApiKey, User
from ledgerone.models.ledger import Journal
from ledgerone.modules.documents.models import SourceDocument
from ledgerone.services.context import AccessContext


class AuditTraceError(ValueError):
    pass


def _decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _iso(value):
    return value.isoformat() if value else None


def _actor_label(actor_type: str, actor_id: str | None) -> str:
    if not actor_id:
        return actor_type or "system"
    if actor_type == "user":
        row = db.session.get(User, actor_id)
        if row:
            return f"{row.name} <{row.email}>"
    if actor_type == "api_key":
        row = db.session.get(ApiKey, actor_id)
        if row:
            return f"API key: {row.name}"
    return f"{actor_type}: {actor_id}"


class AuditTraceService:
    PERMISSIONS = {
        "sales_invoice": "sales.read",
        "purchase_bill": "purchases.read",
        "expense_claim": "expense_claims.read",
        "bank_transaction": "banking.read",
        "journal": "ledger.read",
    }

    @staticmethod
    def build(context: AccessContext, entity_type: str, entity_id: str) -> dict:
        entity_type = (entity_type or "").strip().lower()
        entity_id = (entity_id or "").strip()
        permission = AuditTraceService.PERMISSIONS.get(entity_type)
        if not permission or not entity_id:
            raise AuditTraceError("Unsupported or missing audit-trace target")
        if not context.can(permission):
            raise PermissionError(permission)

        target, journal, lineage = AuditTraceService._target(context, entity_type, entity_id)
        evidence = AuditTraceService._evidence(context, entity_type, entity_id, journal)
        events = AuditTraceService._events(context, lineage, journal, evidence)
        return {
            "target": target,
            "origin": target.get("origin"),
            "journal": AuditTraceService._journal(journal) if journal else None,
            "evidence": evidence,
            "events": events,
        }

    @staticmethod
    def _target(context: AccessContext, entity_type: str, entity_id: str):
        org_id = context.organisation_id
        lineage = [(entity_type, entity_id)]

        if entity_type == "sales_invoice":
            from ledgerone.modules.sales.models import SalesInvoice
            from ledgerone.modules.sales.order_models import SalesOrder
            from ledgerone.modules.sales.quote_models import SalesQuote

            row = db.session.get(SalesInvoice, entity_id)
            if not row or row.organisation_id != org_id:
                raise AuditTraceError("Sales invoice not found")
            metadata = row.metadata_json or {}
            origin = {"label": "Direct sales invoice entry", "entity_type": None, "entity_id": None, "reference": None}
            if metadata.get("source_sales_order_id"):
                source = db.session.get(SalesOrder, metadata["source_sales_order_id"])
                origin = {
                    "label": "Converted from sales order",
                    "entity_type": "sales_order",
                    "entity_id": metadata["source_sales_order_id"],
                    "reference": metadata.get("source_sales_order_number") or (source.order_number if source else None),
                }
                lineage.append(("sales_order", origin["entity_id"]))
            elif metadata.get("source_quote_id"):
                source = db.session.get(SalesQuote, metadata["source_quote_id"])
                origin = {
                    "label": "Converted from sales quote",
                    "entity_type": "sales_quote",
                    "entity_id": metadata["source_quote_id"],
                    "reference": metadata.get("source_quote_number") or (source.quote_number if source else None),
                }
                lineage.append(("sales_quote", origin["entity_id"]))
            target = {
                "entity_type": entity_type,
                "entity_id": row.id,
                "table": "sales_invoices",
                "module": "sales",
                "reference": row.invoice_number,
                "date": _iso(row.invoice_date),
                "due_date": _iso(row.due_date),
                "status": row.status,
                "party": row.customer.name,
                "currency": row.currency,
                "subtotal": _decimal(row.subtotal),
                "tax_total": _decimal(row.tax_total),
                "total": _decimal(row.total),
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
                "record_location": f"LedgerOne / Sales / sales_invoices / {row.id}",
                "origin": origin,
            }
            return target, row.posted_journal, lineage

        if entity_type == "purchase_bill":
            from ledgerone.modules.purchases.models import PurchaseBill
            from ledgerone.modules.purchases.order_models import PurchaseOrder

            row = db.session.get(PurchaseBill, entity_id)
            if not row or row.organisation_id != org_id:
                raise AuditTraceError("Purchase bill not found")
            metadata = row.metadata_json or {}
            origin = {"label": "Direct purchase bill entry", "entity_type": None, "entity_id": None, "reference": None}
            if metadata.get("source_purchase_order_id"):
                source = db.session.get(PurchaseOrder, metadata["source_purchase_order_id"])
                origin = {
                    "label": "Converted from purchase order",
                    "entity_type": "purchase_order",
                    "entity_id": metadata["source_purchase_order_id"],
                    "reference": metadata.get("source_purchase_order_number") or (source.order_number if source else None),
                }
                lineage.append(("purchase_order", origin["entity_id"]))
            target = {
                "entity_type": entity_type,
                "entity_id": row.id,
                "table": "purchase_bills",
                "module": "purchases",
                "reference": row.bill_number,
                "date": _iso(row.bill_date),
                "due_date": _iso(row.due_date),
                "status": row.status,
                "party": row.supplier.name,
                "currency": row.currency,
                "subtotal": _decimal(row.subtotal),
                "tax_total": _decimal(row.tax_total),
                "total": _decimal(row.total),
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
                "record_location": f"LedgerOne / Purchases / purchase_bills / {row.id}",
                "origin": origin,
            }
            return target, row.posted_journal, lineage

        if entity_type == "expense_claim":
            from ledgerone.modules.expense_claims.models import ExpenseClaim

            row = db.session.get(ExpenseClaim, entity_id)
            if not row or row.organisation_id != org_id:
                raise AuditTraceError("Expense claim not found")
            target = {
                "entity_type": entity_type,
                "entity_id": row.id,
                "table": "expense_claims",
                "module": "expense_claims",
                "reference": row.claim_number,
                "date": _iso(row.claim_date),
                "due_date": None,
                "status": row.status,
                "party": row.claimant_name,
                "currency": row.currency,
                "subtotal": _decimal(row.subtotal),
                "tax_total": _decimal(row.tax_total),
                "total": _decimal(row.total),
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
                "record_location": f"LedgerOne / Expense Claims / expense_claims / {row.id}",
                "origin": {"label": "Employee expense claim", "entity_type": None, "entity_id": None, "reference": None},
            }
            return target, row.posted_journal, lineage

        if entity_type == "bank_transaction":
            from ledgerone.modules.banking.models import BankTransaction

            row = db.session.get(BankTransaction, entity_id)
            if not row or not row.bank_account or row.bank_account.organisation_id != org_id:
                raise AuditTraceError("Bank transaction not found")
            account = row.bank_account.ledger_account
            target = {
                "entity_type": entity_type,
                "entity_id": row.id,
                "table": "bank_transactions",
                "module": "banking",
                "reference": row.external_id,
                "date": _iso(row.transaction_date),
                "due_date": None,
                "status": row.status,
                "party": row.bank_account.name,
                "currency": row.bank_account.currency,
                "subtotal": None,
                "tax_total": None,
                "total": _decimal(row.amount),
                "created_at": _iso(row.created_at),
                "updated_at": None,
                "record_location": f"LedgerOne / Banking / bank_transactions / {row.id}",
                "origin": {
                    "label": f"Bank transaction from {row.bank_account.institution or row.bank_account.name}",
                    "entity_type": "bank_account",
                    "entity_id": row.bank_account_id,
                    "reference": row.external_id,
                    "ledger_account": f"{account.code} · {account.name}" if account else None,
                },
            }
            return target, row.matched_journal, lineage

        row = db.session.get(Journal, entity_id)
        if not row or row.organisation_id != org_id:
            raise AuditTraceError("Journal not found")
        target = {
            "entity_type": "journal",
            "entity_id": row.id,
            "table": "journals",
            "module": "ledger",
            "reference": row.reference,
            "date": _iso(row.journal_date),
            "due_date": None,
            "status": row.status,
            "party": None,
            "currency": None,
            "subtotal": None,
            "tax_total": None,
            "total": _decimal(row.total_debit),
            "created_at": _iso(row.created_at),
            "updated_at": None,
            "record_location": f"LedgerOne / Ledger / journals / {row.id}",
            "origin": {
                "label": f"Posted by {row.source_module}",
                "entity_type": row.source_module,
                "entity_id": row.source_reference,
                "reference": row.reference,
            },
        }
        return target, row, lineage

    @staticmethod
    def _journal(journal: Journal) -> dict:
        creator = db.session.get(User, journal.created_by_user_id) if journal.created_by_user_id else None
        return {
            "id": journal.id,
            "date": _iso(journal.journal_date),
            "reference": journal.reference,
            "description": journal.description,
            "status": journal.status,
            "source_module": journal.source_module,
            "source_reference": journal.source_reference,
            "reversal_of_id": journal.reversal_of_id,
            "created_at": _iso(journal.created_at),
            "posted_at": _iso(journal.posted_at),
            "created_by_user_id": journal.created_by_user_id,
            "created_by": f"{creator.name} <{creator.email}>" if creator else journal.created_by_user_id,
            "record_location": f"LedgerOne / Ledger / journals / {journal.id}",
            "total_debit": _decimal(journal.total_debit),
            "total_credit": _decimal(journal.total_credit),
            "lines": [
                {
                    "line_number": line.line_number,
                    "account_id": line.account_id,
                    "account_code": line.account.code,
                    "account_name": line.account.name,
                    "account_type": line.account.account_type,
                    "description": line.description,
                    "debit": _decimal(line.debit),
                    "credit": _decimal(line.credit),
                    "currency": line.currency,
                    "foreign_amount": _decimal(line.foreign_amount),
                    "dimensions": line.dimensions or {},
                    "record_location": f"LedgerOne / Ledger / journal_lines / {line.id}",
                }
                for line in sorted(journal.lines, key=lambda item: item.line_number)
            ],
        }

    @staticmethod
    def _evidence(context: AccessContext, entity_type: str, entity_id: str, journal: Journal | None) -> list[dict]:
        conditions = [and_(SourceDocument.entity_type == entity_type, SourceDocument.entity_id == entity_id)]
        if journal:
            conditions.append(and_(SourceDocument.entity_type == "journal", SourceDocument.entity_id == journal.id))
        rows = (
            SourceDocument.query.filter(
                SourceDocument.organisation_id == context.organisation_id,
                or_(*conditions),
            )
            .order_by(SourceDocument.created_at.asc())
            .all()
        )
        uploader_ids = {row.uploaded_by_user_id for row in rows if row.uploaded_by_user_id}
        uploaders = {
            row.id: row
            for row in User.query.filter(User.id.in_(uploader_ids)).all()
        } if uploader_ids else {}
        result = []
        for row in rows:
            uploader = uploaders.get(row.uploaded_by_user_id)
            location = row.reference_url if row.kind == "reference" else row.storage_key
            result.append({
                "id": row.id,
                "kind": row.kind,
                "title": row.title,
                "target_type": row.entity_type,
                "target_id": row.entity_id,
                "original_filename": row.original_filename,
                "storage_key": row.storage_key,
                "reference_url": row.reference_url,
                "location": location,
                "content_type": row.content_type,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
                "uploaded_by_user_id": row.uploaded_by_user_id,
                "uploaded_by": f"{uploader.name} <{uploader.email}>" if uploader else row.uploaded_by_user_id,
                "created_at": _iso(row.created_at),
            })
        return result

    @staticmethod
    def _events(context: AccessContext, lineage: list[tuple[str, str]], journal: Journal | None, evidence: list[dict]) -> list[dict]:
        keys = list(lineage)
        if journal:
            keys.append(("journal", journal.id))
        keys.extend(("source_document", row["id"]) for row in evidence)
        conditions = [and_(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id) for entity_type, entity_id in keys if entity_id]
        if not conditions:
            return []
        rows = (
            AuditEvent.query.filter(
                AuditEvent.organisation_id == context.organisation_id,
                or_(*conditions),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .limit(1000)
            .all()
        )
        return [
            {
                "id": row.id,
                "created_at": _iso(row.created_at),
                "module_id": row.module_id,
                "action": row.action,
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "actor": _actor_label(row.actor_type, row.actor_id),
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "detail": row.detail or {},
            }
            for row in rows
        ]
