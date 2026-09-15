from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import (
    Account,
    Journal,
    OpeningBalanceBatch,
    RecurringJournal,
    RecurringJournalRun,
)
from ledgerone.modules.settings.services import SettingsService
from ledgerone.services.context import AccessContext


def _full_access(app):
    with app.app_context():
        organisation = Organisation.query.one()
        # These tests exercise immutable posted-journal/opening-balance/recurring-ledger
        # controls themselves. Keep the workflow proposal layer out of these fixtures.
        SettingsService.set_module_enabled(
            AccessContext.system(organisation.id),
            "workflows",
            False,
        )
        key, token = ApiKey.issue(
            name="v02-controls",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        return token, accounts


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_posted_journals_cannot_be_edited_or_deleted(client, app):
    token, accounts = _full_access(app)
    response = client.post(
        "/api/v1/ledger/journals",
        headers=_headers(token),
        json={
            "date": "2026-09-14",
            "description": "Immutable journal",
            "lines": [
                {"account_id": accounts["1000"], "debit": "25.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "25.00"},
            ],
        },
    )
    assert response.status_code == 201
    journal_id = response.get_json()["id"]
    assert response.get_json()["immutable"] is True

    with app.app_context():
        journal = db.session.get(Journal, journal_id)
        journal.description = "Attempted edit"
        with pytest.raises(RuntimeError, match="immutable"):
            db.session.commit()
        db.session.rollback()

        journal = db.session.get(Journal, journal_id)
        db.session.delete(journal)
        with pytest.raises(RuntimeError, match="immutable"):
            db.session.commit()
        db.session.rollback()

        journal = db.session.get(Journal, journal_id)
        assert journal is not None
        assert journal.description == "Immutable journal"


def test_opening_balance_wizard_auto_offsets_to_equity(client, app):
    token, accounts = _full_access(app)
    response = client.post(
        "/api/v1/ledger/opening-balances",
        headers=_headers(token),
        json={
            "as_of_date": "2026-04-01",
            "reference": "OPEN-TEST",
            "description": "Migrated opening balances",
            "balancing_account_id": accounts["3000"],
            "entries": [
                {"account_id": accounts["1000"], "debit": "1000.00", "credit": "0"},
                {"account_id": accounts["2000"], "debit": "0", "credit": "200.00"},
            ],
        },
    )
    assert response.status_code == 201
    result = response.get_json()
    assert result["reference"] == "OPEN-TEST"

    with app.app_context():
        batch = OpeningBalanceBatch.query.one()
        journal = db.session.get(Journal, batch.journal_id)
        assert journal.id == result["journal_id"]
        assert journal.metadata_json["opening_balance"] is True
        assert journal.total_debit == Decimal("1000.00")
        assert journal.total_credit == Decimal("1000.00")
        by_account = {
            line.account_id: (line.debit, line.credit)
            for line in journal.lines
        }
        assert by_account[accounts["3000"]] == (Decimal("0.00"), Decimal("800.00"))

    trial = client.get("/api/v1/ledger/trial-balance", headers=_headers(token))
    rows = {row["code"]: row for row in trial.get_json()["rows"]}
    assert rows["1000"]["balance"] == "1000.00"
    assert rows["2000"]["balance"] == "-200.00"
    assert rows["3000"]["balance"] == "-800.00"


def test_opening_balances_respect_locked_periods(client, app):
    token, accounts = _full_access(app)
    headers = _headers(token)
    period = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={"name": "April 2026", "start_date": "2026-04-01", "end_date": "2026-04-30"},
    )
    assert period.status_code == 201
    period_id = period.get_json()["id"]
    assert client.post(
        f"/api/v1/ledger/periods/{period_id}/lock",
        headers=headers,
        json={"locked": True},
    ).status_code == 200

    response = client.post(
        "/api/v1/ledger/opening-balances",
        headers=headers,
        json={
            "as_of_date": "2026-04-01",
            "balancing_account_id": accounts["3000"],
            "entries": [
                {"account_id": accounts["1000"], "debit": "100.00", "credit": "0"},
            ],
        },
    )
    assert response.status_code == 400
    assert "locked period" in response.get_json()["error"]
    with app.app_context():
        assert OpeningBalanceBatch.query.count() == 0
        assert Journal.query.count() == 0


def test_recurring_journal_posts_next_run_and_advances_schedule(client, app):
    token, accounts = _full_access(app)
    headers = _headers(token)
    created = client.post(
        "/api/v1/ledger/recurring",
        headers=headers,
        json={
            "name": "Monthly subscription",
            "description": "Subscription income",
            "reference": "SUB",
            "frequency": "monthly",
            "next_run_date": "2026-01-31",
            "end_date": "2026-02-28",
            "lines": [
                {"account_id": accounts["1000"], "debit": "50.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "50.00"},
            ],
        },
    )
    assert created.status_code == 201
    recurring_id = created.get_json()["id"]

    first = client.post(f"/api/v1/ledger/recurring/{recurring_id}/run", headers=headers)
    assert first.status_code == 201
    assert first.get_json()["scheduled_date"] == "2026-01-31"
    assert first.get_json()["next_run_date"] == "2026-02-28"
    assert first.get_json()["is_active"] is True

    second = client.post(f"/api/v1/ledger/recurring/{recurring_id}/run", headers=headers)
    assert second.status_code == 201
    assert second.get_json()["scheduled_date"] == "2026-02-28"
    assert second.get_json()["next_run_date"] == "2026-03-28"
    assert second.get_json()["is_active"] is False

    third = client.post(f"/api/v1/ledger/recurring/{recurring_id}/run", headers=headers)
    assert third.status_code == 400
    assert "inactive" in third.get_json()["error"]

    with app.app_context():
        schedule = db.session.get(RecurringJournal, recurring_id)
        assert schedule.run_count == 2
        assert RecurringJournalRun.query.filter_by(recurring_journal_id=recurring_id).count() == 2
        assert Journal.query.count() == 2


def test_recurring_run_is_blocked_by_period_lock_without_advancing(client, app):
    token, accounts = _full_access(app)
    headers = _headers(token)
    created = client.post(
        "/api/v1/ledger/recurring",
        headers=headers,
        json={
            "name": "Locked recurring",
            "description": "Should not post",
            "frequency": "monthly",
            "next_run_date": "2026-06-15",
            "lines": [
                {"account_id": accounts["1000"], "debit": "10.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "10.00"},
            ],
        },
    )
    assert created.status_code == 201
    recurring_id = created.get_json()["id"]

    period = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={"name": "June 2026", "start_date": "2026-06-01", "end_date": "2026-06-30"},
    )
    period_id = period.get_json()["id"]
    client.post(
        f"/api/v1/ledger/periods/{period_id}/lock",
        headers=headers,
        json={"locked": True},
    )

    response = client.post(f"/api/v1/ledger/recurring/{recurring_id}/run", headers=headers)
    assert response.status_code == 400
    assert "locked period" in response.get_json()["error"]

    with app.app_context():
        schedule = db.session.get(RecurringJournal, recurring_id)
        assert schedule.next_run_date.isoformat() == "2026-06-15"
        assert schedule.run_count == 0
        assert RecurringJournalRun.query.count() == 0
        assert Journal.query.count() == 0
