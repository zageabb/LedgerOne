from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account, AccountingPeriod, Journal


def _api_credentials(app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="pytest",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        accounts = {
            account.code: account.id
            for account in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        return token, accounts


def test_ledger_api_requires_authentication(client):
    response = client.get("/api/v1/ledger/accounts")
    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_required"


def test_service_key_can_read_accounts_and_post_balanced_journal(client, app):
    token, accounts = _api_credentials(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/ledger/accounts", headers=headers)
    assert response.status_code == 200
    assert len(response.get_json()["accounts"]) >= 12

    posted = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-09-14",
            "reference": "TEST-001",
            "description": "Test income receipt",
            "lines": [
                {"account_id": accounts["1000"], "debit": "100.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "100.00"},
            ],
        },
    )
    assert posted.status_code == 201
    assert posted.get_json()["status"] == "posted"

    trial_balance = client.get("/api/v1/ledger/trial-balance", headers=headers)
    assert trial_balance.status_code == 200
    rows = {row["code"]: row for row in trial_balance.get_json()["rows"]}
    assert rows["1000"]["balance"] == "100.00"
    assert rows["4000"]["balance"] == "-100.00"


def test_unbalanced_journal_is_rejected_without_partial_posting(client, app):
    token, accounts = _api_credentials(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "description": "Should fail",
            "lines": [
                {"account_id": accounts["1000"], "debit": "100.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "90.00"},
            ],
        },
    )
    assert response.status_code == 400
    assert "not balanced" in response.get_json()["error"]

    with app.app_context():
        assert Journal.query.count() == 0


def test_account_from_another_organisation_cannot_be_posted(client, app):
    token, accounts = _api_credentials(app)
    headers = {"Authorization": f"Bearer {token}"}

    with app.app_context():
        other = Organisation(name="Other Ledger", slug="other-ledger")
        db.session.add(other)
        db.session.flush()
        foreign_account = Account(
            organisation_id=other.id,
            code="9999",
            name="Foreign account",
            account_type="asset",
        )
        db.session.add(foreign_account)
        db.session.commit()
        foreign_account_id = foreign_account.id

    response = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "description": "Cross organisation attempt",
            "lines": [
                {"account_id": foreign_account_id, "debit": "10.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "10.00"},
            ],
        },
    )
    assert response.status_code == 400
    assert "Invalid account" in response.get_json()["error"]


def test_locked_accounting_period_blocks_posting(client, app):
    token, accounts = _api_credentials(app)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={"name": "September 2026", "start_date": "2026-09-01", "end_date": "2026-09-30"},
    )
    assert created.status_code == 201
    period_id = created.get_json()["id"]

    locked = client.post(
        f"/api/v1/ledger/periods/{period_id}/lock",
        headers=headers,
        json={"locked": True},
    )
    assert locked.status_code == 200
    assert locked.get_json()["status"] == "locked"

    blocked = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-09-14",
            "description": "Locked period attempt",
            "lines": [
                {"account_id": accounts["1000"], "debit": "25.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "25.00"},
            ],
        },
    )
    assert blocked.status_code == 400
    assert "locked period September 2026" in blocked.get_json()["error"]

    allowed = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-10-01",
            "description": "Open date posting",
            "lines": [
                {"account_id": accounts["1000"], "debit": "25.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "25.00"},
            ],
        },
    )
    assert allowed.status_code == 201

    with app.app_context():
        assert AccountingPeriod.query.one().status == "locked"
        assert Journal.query.count() == 1


def test_accounting_periods_cannot_overlap(client, app):
    token, _ = _api_credentials(app)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={"name": "September 2026", "start_date": "2026-09-01", "end_date": "2026-09-30"},
    )
    assert first.status_code == 201

    overlap = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={"name": "Quarter overlap", "start_date": "2026-09-15", "end_date": "2026-10-15"},
    )
    assert overlap.status_code == 400
    assert "overlaps September 2026" in overlap.get_json()["error"]


def test_posted_journal_can_be_reversed_once(client, app):
    token, accounts = _api_credentials(app)
    headers = {"Authorization": f"Bearer {token}"}

    posted = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-10-01",
            "reference": "REVTEST",
            "description": "Journal to reverse",
            "lines": [
                {"account_id": accounts["1000"], "debit": "75.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "75.00"},
            ],
        },
    )
    assert posted.status_code == 201
    journal_id = posted.get_json()["id"]

    reversed_response = client.post(
        f"/api/v1/ledger/journals/{journal_id}/reverse",
        headers=headers,
        json={"date": "2026-10-02", "reason": "Correction"},
    )
    assert reversed_response.status_code == 201
    assert reversed_response.get_json()["reversal_of_id"] == journal_id

    second_attempt = client.post(
        f"/api/v1/ledger/journals/{journal_id}/reverse",
        headers=headers,
        json={"date": "2026-10-03"},
    )
    assert second_attempt.status_code == 400
    assert "already been reversed" in second_attempt.get_json()["error"]

    trial_balance = client.get("/api/v1/ledger/trial-balance", headers=headers)
    rows = {row["code"]: row for row in trial_balance.get_json()["rows"]}
    assert rows["1000"]["balance"] == "0.00"
    assert rows["4000"]["balance"] == "0.00"

    with app.app_context():
        assert Journal.query.count() == 2
