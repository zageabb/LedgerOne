from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import (
    NumberAllocation,
    NumberSequence,
    NumberSequenceCounter,
    Organisation,
    new_id,
)
from ledgerone.services.context import AccessContext
from ledgerone.services.numbering import NumberingError, NumberSequenceService


def _context():
    organisation = Organisation.query.one()
    return organisation, AccessContext.system(organisation.id)


def test_numbering_defaults_configuration_and_yearly_reset(app):
    with app.app_context():
        organisation, context = _context()
        rows = NumberSequenceService.list_sequences(context)
        assert len(rows) == 8
        assert NumberSequenceService.peek(organisation.id, "sales_invoice", issue_date=date(2026, 1, 1)) == "INV-0001"

        with pytest.raises(NumberingError, match="Yearly reset requires"):
            NumberSequenceService.update(
                context,
                "sales_invoice",
                prefix="INV-",
                starting_value=1,
                padding=4,
                reset_policy="yearly",
            )

        sequence = NumberSequenceService.update(
            context,
            "sales_invoice",
            prefix="INV-{YYYY}-",
            suffix="",
            starting_value=1,
            padding=4,
            reset_policy="yearly",
        )
        assert NumberSequenceService.serialise(sequence, as_of=date(2026, 1, 1))["next_number"] == "INV-2026-0001"

        first_2026 = NumberSequenceService.allocate_for_entity(
            context,
            "sales_invoice",
            issue_date=date(2026, 2, 1),
            entity_type="sales_invoice",
            entity_id=new_id(),
        )
        first_2027 = NumberSequenceService.allocate_for_entity(
            context,
            "sales_invoice",
            issue_date=date(2027, 2, 1),
            entity_type="sales_invoice",
            entity_id=new_id(),
        )
        db.session.commit()

        assert first_2026.formatted_number == "INV-2026-0001"
        assert first_2027.formatted_number == "INV-2027-0001"
        assert first_2026.sequence_value == first_2027.sequence_value == 1
        assert first_2026.reset_key == "2026"
        assert first_2027.reset_key == "2027"

        with pytest.raises(NumberingError, match="Starting value cannot change"):
            NumberSequenceService.update(
                context,
                "sales_invoice",
                prefix="INV-{YYYY}-",
                starting_value=10,
                padding=4,
                reset_policy="yearly",
            )


def test_issued_and_void_numbers_are_retained_and_gap_report_distinguishes_voids(app):
    with app.app_context():
        _, context = _context()
        first = NumberSequenceService.allocate_for_entity(
            context,
            "sales_invoice",
            issue_date=date(2026, 9, 15),
            entity_type="sales_invoice",
            entity_id=new_id(),
        )
        db.session.commit()
        voided = NumberSequenceService.void_next(
            context,
            "sales_invoice",
            issue_date=date(2026, 9, 15),
            reason="Cancelled paper invoice before issue",
        )
        third = NumberSequenceService.allocate_for_entity(
            context,
            "sales_invoice",
            issue_date=date(2026, 9, 15),
            entity_type="sales_invoice",
            entity_id=new_id(),
            commit=True,
        )

        assert first.formatted_number == "INV-0001"
        assert voided.formatted_number == "INV-0002"
        assert voided.status == "void"
        assert third.formatted_number == "INV-0003"

        history = NumberSequenceService.list_allocations(context, sequence_key="sales_invoice")
        assert {row.formatted_number: row.status for row in history} == {
            "INV-0001": "issued",
            "INV-0002": "void",
            "INV-0003": "issued",
        }
        report = NumberSequenceService.gap_report(context, "sales_invoice")
        assert report["periods"][0]["missing_values"] == []
        assert report["periods"][0]["void"] == ["INV-0002"]


def test_failed_transaction_rolls_back_number_and_counter(app):
    with app.app_context():
        organisation, context = _context()
        allocation = NumberSequenceService.allocate_for_entity(
            context,
            "sales_invoice",
            issue_date=date(2026, 9, 15),
            entity_type="sales_invoice",
            entity_id=new_id(),
        )
        assert allocation.formatted_number == "INV-0001"
        db.session.rollback()
        assert NumberAllocation.query.count() == 0
        assert NumberSequenceService.peek(
            organisation.id,
            "sales_invoice",
            issue_date=date(2026, 9, 15),
        ) == "INV-0001"


def test_number_allocation_identity_is_append_only(app):
    with app.app_context():
        _, context = _context()
        allocation = NumberSequenceService.allocate_for_entity(
            context,
            "sales_invoice",
            issue_date=date(2026, 9, 15),
            entity_type="sales_invoice",
            entity_id=new_id(),
            commit=True,
        )
        allocation.formatted_number = "MUTATED"
        with pytest.raises(NumberingError, match="identity is immutable"):
            db.session.commit()
        db.session.rollback()

        allocation = db.session.get(NumberAllocation, allocation.id)
        assert allocation.formatted_number == "INV-0001"
        db.session.delete(allocation)
        with pytest.raises(NumberingError, match="append-only"):
            db.session.commit()
        db.session.rollback()


def test_manual_number_registration_is_retained_and_cannot_be_reused(app):
    with app.app_context():
        _, context = _context()
        entity_id = new_id()
        manual = NumberSequenceService.register_manual(
            context,
            "sales_invoice",
            formatted_number="LEGACY-100",
            issue_date=date(2026, 9, 15),
            entity_type="sales_invoice",
            entity_id=entity_id,
            commit=True,
        )
        assert manual.manual_override is True
        assert manual.sequence_value is None

        with pytest.raises(NumberingError, match="already been used"):
            NumberSequenceService.register_manual(
                context,
                "sales_invoice",
                formatted_number="LEGACY-100",
                issue_date=date(2026, 9, 15),
                entity_type="sales_invoice",
                entity_id=new_id(),
            )
        db.session.rollback()
        assert NumberAllocation.query.filter_by(formatted_number="LEGACY-100").count() == 1


def test_gap_report_detects_counter_gaps(app):
    with app.app_context():
        organisation, context = _context()
        sequence = NumberSequenceService.get(organisation.id, "sales_invoice")
        counter = NumberSequenceCounter(
            organisation_id=organisation.id,
            sequence_id=sequence.id,
            reset_key="GLOBAL",
            next_value=3,
        )
        db.session.add(counter)
        db.session.commit()

        allocation = NumberSequenceService.allocate_for_entity(
            context,
            "sales_invoice",
            issue_date=date(2026, 9, 15),
            entity_type="sales_invoice",
            entity_id=new_id(),
            commit=True,
        )
        assert allocation.formatted_number == "INV-0003"
        report = NumberSequenceService.gap_report(context, "sales_invoice")
        assert report["periods"][0]["missing_values"] == [1, 2]


def test_atomic_counter_allocation_is_unique_under_concurrent_sessions(app):
    with app.app_context():
        organisation, context = _context()
        sequence = NumberSequenceService.get(organisation.id, "sales_invoice")
        db.session.add(
            NumberSequenceCounter(
                organisation_id=organisation.id,
                sequence_id=sequence.id,
                reset_key="GLOBAL",
                next_value=1,
            )
        )
        db.session.commit()
        organisation_id = organisation.id

    def allocate(index):
        with app.app_context():
            context = AccessContext.system(organisation_id)
            allocation = NumberSequenceService.allocate_for_entity(
                context,
                "sales_invoice",
                issue_date=date(2026, 9, 15),
                entity_type="sales_invoice",
                entity_id=f"concurrent-{index}",
                commit=True,
            )
            number = allocation.formatted_number
            db.session.remove()
            return number

    with ThreadPoolExecutor(max_workers=4) as pool:
        numbers = list(pool.map(allocate, range(4)))

    assert len(numbers) == len(set(numbers)) == 4
    assert sorted(numbers) == ["INV-0001", "INV-0002", "INV-0003", "INV-0004"]
    with app.app_context():
        assert NumberAllocation.query.filter_by(
            organisation_id=organisation_id,
            sequence_key="sales_invoice",
        ).count() == 4
