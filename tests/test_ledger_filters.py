from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account


def _key_and_accounts(app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="ledger-filter-test",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        for code, name, account_type in [
            ("5400", "Insurance", "expense"),
            ("5500", "Software", "expense"),
            ("5600", "Consulting income", "income"),
        ]:
            db.session.add(
                Account(
                    organisation_id=organisation.id,
                    code=code,
                    name=name,
                    account_type=account_type,
                )
            )
        db.session.commit()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        return token, accounts


def test_accounts_support_search_type_and_pagination(client, app):
    token, _ = _key_and_accounts(app)
    headers = {"Authorization": f"Bearer {token}"}

    filtered = client.get(
        "/api/v1/ledger/accounts?q=insur&account_type=expense&per_page=1&page=1",
        headers=headers,
    )
    assert filtered.status_code == 200
    payload = filtered.get_json()
    assert [row["code"] for row in payload["accounts"]] == ["5400"]
    assert payload["pagination"]["page"] == 1
    assert payload["pagination"]["per_page"] == 1
    assert payload["pagination"]["total"] == 1


def test_journals_support_source_date_search_and_pagination(client, app):
    token, accounts = _key_and_accounts(app)
    headers = {"Authorization": f"Bearer {token}"}
    for index, day in enumerate(["2026-09-10", "2026-09-11", "2026-09-12"], start=1):
        response = client.post(
            "/api/v1/ledger/journals",
            headers=headers,
            json={
                "date": day,
                "reference": f"FILTER-{index}",
                "description": f"Filter journal {index}",
                "source_module": "api",
                "lines": [
                    {"account_id": accounts["1000"], "debit": "1.00", "credit": "0"},
                    {"account_id": accounts["4000"], "debit": "0", "credit": "1.00"},
                ],
            },
        )
        assert response.status_code == 201

    page = client.get(
        "/api/v1/ledger/journals?source_module=api&from_date=2026-09-11&to_date=2026-09-12&q=Filter&per_page=1&page=2",
        headers=headers,
    )
    assert page.status_code == 200
    payload = page.get_json()
    assert payload["pagination"]["total"] == 2
    assert payload["pagination"]["page"] == 2
    assert len(payload["journals"]) == 1
    assert payload["journals"][0]["reference"] == "FILTER-2"


def test_invalid_journal_date_filter_returns_400(client, app):
    token, _ = _key_and_accounts(app)
    response = client.get(
        "/api/v1/ledger/journals?from_date=not-a-date",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
