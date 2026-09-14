from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account, Journal


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
