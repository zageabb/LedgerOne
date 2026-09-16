from __future__ import annotations

from datetime import date

from ledgerone.models.core import NumberAllocation
from ledgerone.modules.sales.credit_models import SalesCreditNote
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.services.context import AccessContext
from ledgerone.services.numbering import NumberingError, NumberSequenceService


def _matches_controlled_series(
    context: AccessContext,
    sequence_key: str,
    number: str,
    issue_date: date,
) -> bool:
    """Return True when a supplied number belongs to the configured controlled series."""
    sequence = NumberSequenceService.get(context.organisation_id, sequence_key)
    year = str(issue_date.year)
    prefix = sequence.prefix.replace("{YYYY}", year).replace("{YY}", year[-2:])
    suffix = sequence.suffix.replace("{YYYY}", year).replace("{YY}", year[-2:])
    if not number.startswith(prefix):
        return False
    if suffix and not number.endswith(suffix):
        return False
    end = len(number) - len(suffix) if suffix else len(number)
    middle = number[len(prefix):end]
    if not middle.isdigit():
        return False
    value = int(middle)
    return NumberSequenceService._render(sequence, value, issue_date) == number


def _assign_number(
    context: AccessContext,
    *,
    sequence_key: str,
    issue_date: date,
    entity_type: str,
    entity_id: str,
    requested_number: str | None,
    model,
    number_field: str,
    date_field: str,
) -> str:
    """Assign an issued number without consuming numbers for unposted workflow proposals.

    A blank number uses the controlled series. A supplied number outside the configured
    series is retained as a manual/legacy override in allocation history. A supplied
    number that belongs to the controlled series may only be the exact next number; this
    prevents a user from jumping the counter or creating a future collision.

    Existing documents from before controlled numbering are adopted lazily when the next
    automatic number reaches them. That makes upgrades safe without rewriting issued
    source documents.
    """
    clean_number = (requested_number or "").strip()
    if clean_number:
        if model.query.filter_by(
            organisation_id=context.organisation_id,
            **{number_field: clean_number},
        ).first():
            raise NumberingError("Document number already exists")

        next_number = NumberSequenceService.peek(
            context.organisation_id,
            sequence_key,
            issue_date=issue_date,
        )
        if clean_number == next_number:
            allocation = NumberSequenceService.allocate_for_entity(
                context,
                sequence_key,
                issue_date=issue_date,
                entity_type=entity_type,
                entity_id=entity_id,
                commit=False,
            )
            return allocation.formatted_number

        if _matches_controlled_series(context, sequence_key, clean_number, issue_date):
            raise NumberingError(
                f"{clean_number} belongs to LedgerOne's controlled number series but is not "
                f"the next available number ({next_number}). Leave the field blank to allocate "
                "the next controlled number automatically."
            )

        NumberSequenceService.register_manual(
            context,
            sequence_key,
            formatted_number=clean_number,
            issue_date=issue_date,
            entity_type=entity_type,
            entity_id=entity_id,
            commit=False,
        )
        return clean_number

    # Existing installations may already contain documents such as INV-0001 without
    # allocation-history rows. Consume/adopt those issued numbers until the sequence
    # reaches a genuinely unused number for the new document.
    for _ in range(10_000):
        next_number = NumberSequenceService.peek(
            context.organisation_id,
            sequence_key,
            issue_date=issue_date,
        )
        existing = model.query.filter_by(
            organisation_id=context.organisation_id,
            **{number_field: next_number},
        ).first()
        if existing is None:
            allocation = NumberSequenceService.allocate_for_entity(
                context,
                sequence_key,
                issue_date=issue_date,
                entity_type=entity_type,
                entity_id=entity_id,
                commit=False,
            )
            return allocation.formatted_number

        existing_allocation = NumberAllocation.query.filter_by(
            organisation_id=context.organisation_id,
            sequence_key=sequence_key,
            formatted_number=next_number,
        ).first()
        if existing_allocation is not None:
            raise NumberingError(
                "Numbering counter conflicts with existing allocation history. Review the "
                "number-sequence configuration before posting another document."
            )

        legacy_date = getattr(existing, date_field)
        adopted = NumberSequenceService.allocate_for_entity(
            context,
            sequence_key,
            issue_date=legacy_date,
            entity_type=entity_type,
            entity_id=existing.id,
            commit=False,
        )
        if adopted.formatted_number != next_number:
            raise NumberingError(
                "Existing document numbering no longer matches the configured sequence. "
                "Review the number-sequence configuration before automatic allocation."
            )

    raise NumberingError("Could not find an available controlled document number")


def assign_sales_invoice_number(
    context: AccessContext,
    *,
    invoice_id: str,
    invoice_date: date,
    requested_number: str | None,
) -> str:
    return _assign_number(
        context,
        sequence_key="sales_invoice",
        issue_date=invoice_date,
        entity_type="sales_invoice",
        entity_id=invoice_id,
        requested_number=requested_number,
        model=SalesInvoice,
        number_field="invoice_number",
        date_field="invoice_date",
    )


def assign_sales_credit_number(
    context: AccessContext,
    *,
    credit_id: str,
    credit_date: date,
    requested_number: str | None,
) -> str:
    return _assign_number(
        context,
        sequence_key="sales_credit_note",
        issue_date=credit_date,
        entity_type="sales_credit_note",
        entity_id=credit_id,
        requested_number=requested_number,
        model=SalesCreditNote,
        number_field="credit_number",
        date_field="credit_date",
    )
