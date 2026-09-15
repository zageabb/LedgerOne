from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date

from sqlalchemy import event, inspect as sa_inspect, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ledgerone.extensions import db
from ledgerone.models.core import (
    NumberAllocation,
    NumberSequence,
    NumberSequenceCounter,
    utcnow,
)
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


DEFAULT_SEQUENCES = {
    "sales_invoice": {"label": "Sales invoices", "prefix": "INV-", "suffix": "", "padding": 4},
    "sales_credit_note": {"label": "Sales credit notes", "prefix": "SCN-", "suffix": "", "padding": 4},
    "purchase_bill": {"label": "Purchase bills", "prefix": "BILL-", "suffix": "", "padding": 4},
    "purchase_credit_note": {"label": "Purchase credit notes", "prefix": "PCN-", "suffix": "", "padding": 4},
    "sales_quote": {"label": "Sales quotes", "prefix": "QUO-", "suffix": "", "padding": 4},
    "sales_order": {"label": "Sales orders", "prefix": "SO-", "suffix": "", "padding": 4},
    "purchase_order": {"label": "Purchase orders", "prefix": "PO-", "suffix": "", "padding": 4},
    "expense_claim": {"label": "Expense claims", "prefix": "EXP-", "suffix": "", "padding": 4},
}

ALLOWED_RESET_POLICIES = frozenset({"never", "yearly"})
ALLOWED_YEAR_TOKENS = frozenset({"{YYYY}", "{YY}"})
ALLOCATION_TERMINAL_STATUSES = frozenset({"issued", "void"})


class NumberingError(ValueError):
    pass


_allocation_transition_authorised: ContextVar[bool] = ContextVar(
    "ledgerone_number_allocation_transition_authorised", default=False
)
_guard_installed = False


@contextmanager
def _allocation_transition_scope():
    token = _allocation_transition_authorised.set(True)
    try:
        yield
    finally:
        _allocation_transition_authorised.reset(token)


def _changed_fields(target) -> set[str]:
    state = sa_inspect(target)
    return {
        attr.key
        for attr in state.mapper.column_attrs
        if state.attrs[attr.key].history.has_changes()
    }


def _allocation_status_before(target: NumberAllocation) -> str | None:
    history = sa_inspect(target).attrs.status.history
    old = [value for value in history.deleted if value is not None]
    if old:
        return old[0]
    return target.status if sa_inspect(target).persistent else None


def _guard_number_allocations(session: Session, flush_context, instances) -> None:
    identity_fields = {
        "organisation_id",
        "sequence_id",
        "sequence_key",
        "reset_key",
        "sequence_value",
        "formatted_number",
        "issue_date",
        "manual_override",
        "allocated_by_user_id",
        "allocated_at",
    }
    transition_fields = {"status", "entity_type", "entity_id", "reason", "issued_at", "voided_at"}

    for obj in list(session.deleted):
        if isinstance(obj, NumberAllocation):
            raise NumberingError("Number allocation history is append-only and cannot be deleted")

    for obj in list(session.dirty):
        if not isinstance(obj, NumberAllocation):
            continue
        changed = _changed_fields(obj)
        if not changed:
            continue
        if changed & identity_fields:
            raise NumberingError("Issued/reserved number identity is immutable")
        old_status = _allocation_status_before(obj)
        if old_status in ALLOCATION_TERMINAL_STATUSES:
            raise NumberingError("Issued or void number allocation history is immutable")
        if not _allocation_transition_authorised.get():
            raise NumberingError("Number allocation state can only change through NumberSequenceService")
        if changed - transition_fields:
            raise NumberingError("Unsupported number allocation mutation")
        if old_status != "reserved" or obj.status not in ALLOCATION_TERMINAL_STATUSES:
            raise NumberingError("Only reserved numbers may transition to issued or void")
        if obj.status == "issued" and (not obj.entity_type or not obj.entity_id or not obj.issued_at):
            raise NumberingError("Issued number must be linked to its business document")
        if obj.status == "void" and (not (obj.reason or "").strip() or not obj.voided_at):
            raise NumberingError("Voiding a number requires a reason")


def install_numbering_guards() -> None:
    global _guard_installed
    if _guard_installed:
        return
    event.listen(Session, "before_flush", _guard_number_allocations)
    _guard_installed = True


class NumberSequenceService:
    """Controlled, auditable document-number allocation.

    Counters are incremented with compare-and-swap UPDATE statements rather than a
    read/increment/write cycle. The counter change and allocation row live in the caller's
    transaction, so a failed document posting rolls both back together.
    """

    @staticmethod
    def _validate_key(sequence_key: str) -> str:
        key = (sequence_key or "").strip()
        if key not in DEFAULT_SEQUENCES:
            raise NumberingError("Unknown numbering sequence")
        return key

    @staticmethod
    def _validate_config(*, prefix, suffix, starting_value, padding, reset_policy):
        prefix = str(prefix or "").strip()
        suffix = str(suffix or "").strip()
        reset_policy = str(reset_policy or "never").strip().lower()
        if len(prefix) > 40 or len(suffix) > 40:
            raise NumberingError("Numbering prefix and suffix must be 40 characters or fewer")
        if any(ch in prefix + suffix for ch in "\r\n\t"):
            raise NumberingError("Numbering prefix and suffix cannot contain control whitespace")
        tokens = set(re.findall(r"\{[^{}]+\}", prefix + suffix))
        if tokens - ALLOWED_YEAR_TOKENS:
            raise NumberingError("Only {YYYY} and {YY} numbering tokens are supported")
        if reset_policy not in ALLOWED_RESET_POLICIES:
            raise NumberingError("Reset policy must be never or yearly")
        if reset_policy == "yearly" and not (tokens & ALLOWED_YEAR_TOKENS):
            raise NumberingError("Yearly reset requires {YYYY} or {YY} in the prefix or suffix")
        try:
            starting_value = int(starting_value)
            padding = int(padding)
        except (TypeError, ValueError) as exc:
            raise NumberingError("Starting value and padding must be whole numbers") from exc
        if starting_value < 1:
            raise NumberingError("Starting value must be at least 1")
        if padding < 1 or padding > 12:
            raise NumberingError("Padding must be between 1 and 12")
        return prefix, suffix, starting_value, padding, reset_policy

    @staticmethod
    def seed_defaults(organisation_id: str, *, commit: bool = True):
        from sqlalchemy import inspect

        if not inspect(db.engine).has_table("number_sequences"):
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
                starting_value=1,
                padding=config["padding"],
                reset_policy="never",
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
    def get(organisation_id: str, sequence_key: str) -> NumberSequence:
        key = NumberSequenceService._validate_key(sequence_key)
        NumberSequenceService.seed_defaults(organisation_id, commit=False)
        row = NumberSequence.query.filter_by(
            organisation_id=organisation_id,
            sequence_key=key,
        ).first()
        if not row:
            raise NumberingError("Numbering sequence is unavailable")
        if not row.is_active:
            raise NumberingError(f"Numbering sequence {key} is disabled")
        return row

    @staticmethod
    def _reset_key(sequence: NumberSequence, issue_date: date) -> str:
        return str(issue_date.year) if sequence.reset_policy == "yearly" else "GLOBAL"

    @staticmethod
    def _render(sequence: NumberSequence, value: int, issue_date: date) -> str:
        year = str(issue_date.year)
        short_year = year[-2:]
        prefix = sequence.prefix.replace("{YYYY}", year).replace("{YY}", short_year)
        suffix = sequence.suffix.replace("{YYYY}", year).replace("{YY}", short_year)
        return f"{prefix}{str(int(value)).zfill(sequence.padding)}{suffix}"

    @staticmethod
    def _counter(sequence: NumberSequence, reset_key: str) -> NumberSequenceCounter:
        row = NumberSequenceCounter.query.filter_by(
            sequence_id=sequence.id,
            reset_key=reset_key,
        ).first()
        if row:
            return row
        try:
            with db.session.begin_nested():
                row = NumberSequenceCounter(
                    organisation_id=sequence.organisation_id,
                    sequence_id=sequence.id,
                    reset_key=reset_key,
                    next_value=sequence.starting_value,
                )
                db.session.add(row)
                db.session.flush()
                return row
        except IntegrityError:
            row = NumberSequenceCounter.query.filter_by(
                sequence_id=sequence.id,
                reset_key=reset_key,
            ).first()
            if not row:
                raise
            return row

    @staticmethod
    def peek(organisation_id: str, sequence_key: str, *, issue_date: date | None = None) -> str:
        issue_date = issue_date or date.today()
        sequence = NumberSequenceService.get(organisation_id, sequence_key)
        reset_key = NumberSequenceService._reset_key(sequence, issue_date)
        counter = NumberSequenceCounter.query.filter_by(
            sequence_id=sequence.id,
            reset_key=reset_key,
        ).first()
        value = counter.next_value if counter else sequence.starting_value
        return NumberSequenceService._render(sequence, value, issue_date)

    @staticmethod
    def reserve(
        context: AccessContext,
        sequence_key: str,
        *,
        issue_date: date,
    ) -> NumberAllocation:
        if not context.organisation_id:
            raise NumberingError("An organisation is required")
        sequence = NumberSequenceService.get(context.organisation_id, sequence_key)
        reset_key = NumberSequenceService._reset_key(sequence, issue_date)
        counter = NumberSequenceService._counter(sequence, reset_key)

        for _ in range(20):
            db.session.refresh(counter)
            value = int(counter.next_value)
            result = db.session.execute(
                sa_update(NumberSequenceCounter)
                .where(
                    NumberSequenceCounter.id == counter.id,
                    NumberSequenceCounter.next_value == value,
                )
                .values(next_value=value + 1, updated_at=utcnow())
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                db.session.expire(counter)
                continue
            formatted = NumberSequenceService._render(sequence, value, issue_date)
            allocation = NumberAllocation(
                organisation_id=context.organisation_id,
                sequence_id=sequence.id,
                sequence_key=sequence.sequence_key,
                reset_key=reset_key,
                sequence_value=value,
                formatted_number=formatted,
                status="reserved",
                issue_date=issue_date,
                allocated_by_user_id=context.user_id,
            )
            db.session.add(allocation)
            db.session.flush()
            return allocation
        raise NumberingError("Could not allocate a unique document number; retry the transaction")

    @staticmethod
    def issue(
        context: AccessContext,
        allocation: NumberAllocation,
        *,
        entity_type: str,
        entity_id: str,
    ) -> NumberAllocation:
        if allocation.organisation_id != context.organisation_id:
            raise NumberingError("Number allocation belongs to another organisation")
        if allocation.status != "reserved":
            raise NumberingError("Only a reserved number can be issued")
        with _allocation_transition_scope():
            allocation.status = "issued"
            allocation.entity_type = (entity_type or "").strip()
            allocation.entity_id = (entity_id or "").strip()
            allocation.issued_at = utcnow()
            db.session.flush()
        record_audit_event(
            context,
            module_id="settings",
            action="document_number_issued",
            entity_type="number_allocation",
            entity_id=allocation.id,
            detail={
                "sequence_key": allocation.sequence_key,
                "number": allocation.formatted_number,
                "business_entity_type": allocation.entity_type,
                "business_entity_id": allocation.entity_id,
            },
        )
        return allocation

    @staticmethod
    def allocate_for_entity(
        context: AccessContext,
        sequence_key: str,
        *,
        issue_date: date,
        entity_type: str,
        entity_id: str,
        commit: bool = False,
    ) -> NumberAllocation:
        allocation = NumberSequenceService.reserve(
            context,
            sequence_key,
            issue_date=issue_date,
        )
        NumberSequenceService.issue(
            context,
            allocation,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        if commit:
            db.session.commit()
        return allocation

    @staticmethod
    def register_manual(
        context: AccessContext,
        sequence_key: str,
        *,
        formatted_number: str,
        issue_date: date,
        entity_type: str,
        entity_id: str,
        commit: bool = False,
    ) -> NumberAllocation:
        sequence = NumberSequenceService.get(context.organisation_id, sequence_key)
        number = (formatted_number or "").strip()
        if not number:
            raise NumberingError("Document number is required")
        if NumberAllocation.query.filter_by(
            organisation_id=context.organisation_id,
            sequence_key=sequence.sequence_key,
            formatted_number=number,
        ).first():
            raise NumberingError("Document number has already been used or reserved")
        allocation = NumberAllocation(
            organisation_id=context.organisation_id,
            sequence_id=sequence.id,
            sequence_key=sequence.sequence_key,
            reset_key=NumberSequenceService._reset_key(sequence, issue_date),
            sequence_value=None,
            formatted_number=number,
            status="issued",
            issue_date=issue_date,
            entity_type=(entity_type or "").strip(),
            entity_id=(entity_id or "").strip(),
            manual_override=True,
            allocated_by_user_id=context.user_id,
            issued_at=utcnow(),
        )
        db.session.add(allocation)
        db.session.flush()
        record_audit_event(
            context,
            module_id="settings",
            action="manual_document_number_registered",
            entity_type="number_allocation",
            entity_id=allocation.id,
            detail={
                "sequence_key": allocation.sequence_key,
                "number": allocation.formatted_number,
                "business_entity_type": allocation.entity_type,
                "business_entity_id": allocation.entity_id,
            },
        )
        if commit:
            db.session.commit()
        return allocation

    @staticmethod
    def void_next(
        context: AccessContext,
        sequence_key: str,
        *,
        issue_date: date,
        reason: str,
    ) -> NumberAllocation:
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        reason = (reason or "").strip()
        if not reason:
            raise NumberingError("Voiding a number requires a reason")
        allocation = NumberSequenceService.reserve(
            context,
            sequence_key,
            issue_date=issue_date,
        )
        with _allocation_transition_scope():
            allocation.status = "void"
            allocation.reason = reason
            allocation.voided_at = utcnow()
            db.session.flush()
        record_audit_event(
            context,
            module_id="settings",
            action="document_number_voided",
            entity_type="number_allocation",
            entity_id=allocation.id,
            detail={
                "sequence_key": allocation.sequence_key,
                "number": allocation.formatted_number,
                "reason": reason,
            },
        )
        db.session.commit()
        return allocation

    @staticmethod
    def list_sequences(context: AccessContext) -> list[NumberSequence]:
        if not context.organisation_id:
            raise NumberingError("An organisation is required")
        NumberSequenceService.seed_defaults(context.organisation_id)
        rows = NumberSequence.query.filter_by(organisation_id=context.organisation_id).all()
        by_key = {row.sequence_key: row for row in rows}
        return [by_key[key] for key in DEFAULT_SEQUENCES if key in by_key]

    @staticmethod
    def list_allocations(
        context: AccessContext,
        *,
        sequence_key: str | None = None,
        limit: int = 500,
    ) -> list[NumberAllocation]:
        query = NumberAllocation.query.filter_by(organisation_id=context.organisation_id)
        if sequence_key:
            query = query.filter_by(sequence_key=NumberSequenceService._validate_key(sequence_key))
        return query.order_by(NumberAllocation.allocated_at.desc()).limit(limit).all()

    @staticmethod
    def update(
        context: AccessContext,
        sequence_key: str,
        *,
        prefix,
        suffix="",
        starting_value=1,
        padding=4,
        reset_policy="never",
    ) -> NumberSequence:
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        key = NumberSequenceService._validate_key(sequence_key)
        prefix, suffix, starting_value, padding, reset_policy = NumberSequenceService._validate_config(
            prefix=prefix,
            suffix=suffix,
            starting_value=starting_value,
            padding=padding,
            reset_policy=reset_policy,
        )
        sequence = NumberSequenceService.get(context.organisation_id, key)
        has_allocations = NumberAllocation.query.filter_by(sequence_id=sequence.id).first() is not None
        if has_allocations and starting_value != sequence.starting_value:
            raise NumberingError("Starting value cannot change after numbers have been allocated")
        if has_allocations and reset_policy != sequence.reset_policy:
            raise NumberingError("Reset policy cannot change after numbers have been allocated")
        before = NumberSequenceService.serialise(sequence)
        sequence.prefix = prefix
        sequence.suffix = suffix
        sequence.starting_value = starting_value
        sequence.padding = padding
        sequence.reset_policy = reset_policy
        db.session.flush()
        record_audit_event(
            context,
            module_id="settings",
            action="number_sequence_updated",
            entity_type="number_sequence",
            entity_id=sequence.id,
            detail={"sequence_key": key, "before": before, "after": NumberSequenceService.serialise(sequence)},
        )
        db.session.commit()
        return sequence

    @staticmethod
    def serialise(sequence: NumberSequence, *, as_of: date | None = None) -> dict:
        as_of = as_of or date.today()
        reset_key = NumberSequenceService._reset_key(sequence, as_of)
        counter = NumberSequenceCounter.query.filter_by(
            sequence_id=sequence.id,
            reset_key=reset_key,
        ).first()
        next_value = counter.next_value if counter else sequence.starting_value
        return {
            "key": sequence.sequence_key,
            "label": DEFAULT_SEQUENCES.get(sequence.sequence_key, {}).get("label", sequence.sequence_key),
            "prefix": sequence.prefix,
            "suffix": sequence.suffix,
            "starting_value": sequence.starting_value,
            "padding": sequence.padding,
            "reset_policy": sequence.reset_policy,
            "is_active": sequence.is_active,
            "reset_key": reset_key,
            "next_value": next_value,
            "next_number": NumberSequenceService._render(sequence, next_value, as_of),
        }

    @staticmethod
    def gap_report(
        context: AccessContext,
        sequence_key: str,
        *,
        reset_key: str | None = None,
    ) -> dict:
        sequence = NumberSequenceService.get(context.organisation_id, sequence_key)
        query = NumberAllocation.query.filter_by(
            organisation_id=context.organisation_id,
            sequence_id=sequence.id,
        ).filter(NumberAllocation.sequence_value.is_not(None))
        if reset_key:
            query = query.filter_by(reset_key=reset_key)
        allocations = query.order_by(NumberAllocation.reset_key, NumberAllocation.sequence_value).all()
        grouped: dict[str, list[NumberAllocation]] = {}
        for allocation in allocations:
            grouped.setdefault(allocation.reset_key, []).append(allocation)
        periods = []
        for key, rows in grouped.items():
            values = {int(row.sequence_value) for row in rows}
            highest = max(values)
            missing = [value for value in range(sequence.starting_value, highest + 1) if value not in values]
            periods.append(
                {
                    "reset_key": key,
                    "first_value": min(values),
                    "last_value": highest,
                    "missing_values": missing,
                    "issued": [row.formatted_number for row in rows if row.status == "issued"],
                    "void": [row.formatted_number for row in rows if row.status == "void"],
                }
            )
        return {
            "sequence": NumberSequenceService.serialise(sequence),
            "periods": periods,
            "manual_overrides": [
                row.formatted_number
                for row in NumberSequenceService.list_allocations(
                    context, sequence_key=sequence.sequence_key, limit=1000
                )
                if row.manual_override
            ],
        }
