from __future__ import annotations

from sqlalchemy import inspect

from ledgerone.extensions import db
from ledgerone.models.core import NumberSequence
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


DEFAULT_SEQUENCES = {
    "sales_invoice": {"label": "Sales invoices", "prefix": "INV-", "suffix": "", "padding": 4},
    "sales_quote": {"label": "Sales quotes", "prefix": "QUO-", "suffix": "", "padding": 4},
    "sales_order": {"label": "Sales orders", "prefix": "SO-", "suffix": "", "padding": 4},
    "sales_credit_note": {"label": "Sales credit notes", "prefix": "SCN-", "suffix": "", "padding": 4},
    "purchase_bill": {"label": "Purchase bills", "prefix": "BILL-", "suffix": "", "padding": 4},
    "purchase_order": {"label": "Purchase orders", "prefix": "PO-", "suffix": "", "padding": 4},
    "purchase_credit_note": {"label": "Purchase credit notes", "prefix": "PCN-", "suffix": "", "padding": 4},
    "expense_claim": {"label": "Expense claims", "prefix": "EXP-", "suffix": "", "padding": 4},
}


class NumberSequenceService:
    @staticmethod
    def _validate_key(sequence_key: str) -> str:
        key = (sequence_key or "").strip()
        if key not in DEFAULT_SEQUENCES:
            raise ValueError("Unknown numbering sequence")
        return key

    @staticmethod
    def _validate_values(*, prefix, suffix, next_value, padding):
        prefix = str(prefix or "").strip()
        suffix = str(suffix or "").strip()
        if len(prefix) > 40 or len(suffix) > 40:
            raise ValueError("Numbering prefix and suffix must be 40 characters or fewer")
        if any(ch in prefix + suffix for ch in "\r\n\t"):
            raise ValueError("Numbering prefix and suffix cannot contain control whitespace")
        try:
            next_value = int(next_value)
            padding = int(padding)
        except (TypeError, ValueError) as exc:
            raise ValueError("Next value and padding must be whole numbers") from exc
        if next_value < 1:
            raise ValueError("Next value must be at least 1")
        if padding < 1 or padding > 12:
            raise ValueError("Padding must be between 1 and 12")
        return prefix, suffix, next_value, padding

    @staticmethod
    def seed_defaults(organisation_id: str, *, commit: bool = True):
        inspector = inspect(db.engine)
        if not inspector.has_table("number_sequences"):
            return []
        existing = {
            row.sequence_key: row
            for row in NumberSequence.query.filter_by(organisation_id=organisation_id).all()
        }
        created = []
        for key, config in DEFAULT_SEQUENCES.items():
            if key in existing:
                continue
            row = NumberSequence(
                organisation_id=organisation_id,
                sequence_key=key,
                prefix=config["prefix"],
                suffix=config["suffix"],
                next_value=1,
                padding=config["padding"],
            )
            db.session.add(row)
            created.append(row)
        if created:
            if commit:
                db.session.commit()
            else:
                db.session.flush()
        return created

    @staticmethod
    def list_sequences(organisation_id: str):
        NumberSequenceService.seed_defaults(organisation_id)
        rows = NumberSequence.query.filter_by(organisation_id=organisation_id).all()
        by_key = {row.sequence_key: row for row in rows}
        return [by_key[key] for key in DEFAULT_SEQUENCES if key in by_key]

    @staticmethod
    def get(organisation_id: str, sequence_key: str, *, for_update: bool = False):
        key = NumberSequenceService._validate_key(sequence_key)
        NumberSequenceService.seed_defaults(organisation_id, commit=False)
        query = NumberSequence.query.filter_by(organisation_id=organisation_id, sequence_key=key)
        if for_update:
            query = query.with_for_update()
        row = query.first()
        if row is None:
            config = DEFAULT_SEQUENCES[key]
            row = NumberSequence(
                organisation_id=organisation_id,
                sequence_key=key,
                prefix=config["prefix"],
                suffix=config["suffix"],
                next_value=1,
                padding=config["padding"],
            )
            db.session.add(row)
            db.session.flush()
        return row

    @staticmethod
    def format_number(row: NumberSequence, value: int | None = None) -> str:
        number = row.next_value if value is None else int(value)
        return f"{row.prefix}{str(number).zfill(row.padding)}{row.suffix}"

    @staticmethod
    def peek(organisation_id: str, sequence_key: str) -> str:
        row = NumberSequenceService.get(organisation_id, sequence_key)
        return NumberSequenceService.format_number(row)

    @staticmethod
    def next_number(context: AccessContext, sequence_key: str) -> str:
        row = NumberSequenceService.get(context.organisation_id, sequence_key, for_update=True)
        value = row.next_value
        generated = NumberSequenceService.format_number(row, value)
        row.next_value = value + 1
        db.session.flush()
        return generated

    @staticmethod
    def update(
        context: AccessContext,
        sequence_key: str,
        *,
        prefix,
        suffix="",
        next_value=1,
        padding=4,
    ):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        key = NumberSequenceService._validate_key(sequence_key)
        prefix, suffix, next_value, padding = NumberSequenceService._validate_values(
            prefix=prefix,
            suffix=suffix,
            next_value=next_value,
            padding=padding,
        )
        row = NumberSequenceService.get(context.organisation_id, key, for_update=True)
        before = {
            "prefix": row.prefix,
            "suffix": row.suffix,
            "next_value": row.next_value,
            "padding": row.padding,
        }
        row.prefix = prefix
        row.suffix = suffix
        row.next_value = next_value
        row.padding = padding
        record_audit_event(
            context,
            module_id="settings",
            action="number_sequence_updated",
            entity_type="number_sequence",
            entity_id=row.id,
            detail={
                "sequence_key": key,
                "before": before,
                "after": {
                    "prefix": prefix,
                    "suffix": suffix,
                    "next_value": next_value,
                    "padding": padding,
                },
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def serialise(row: NumberSequence):
        return {
            "key": row.sequence_key,
            "label": DEFAULT_SEQUENCES[row.sequence_key]["label"],
            "prefix": row.prefix,
            "suffix": row.suffix,
            "next_value": row.next_value,
            "padding": row.padding,
            "next_number": NumberSequenceService.format_number(row),
        }
