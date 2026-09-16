from datetime import date

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, NumberAllocation, Organisation


def _login(client):
    response = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert response.status_code == 200


def _full_access_token(app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="numbering-admin-test",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        return token


def test_numbering_settings_page_shows_controlled_series_and_history(client, app):
    _login(client)

    page = client.get("/settings/numbering?sequence_key=sales_invoice")

    assert page.status_code == 200
    assert b"Document numbering" in page.data
    assert b"Sales invoices" in page.data
    assert b"INV-0001" in page.data
    assert b"Gap report" in page.data
    assert b"Allocation history" in page.data
    assert b"Controlled" in page.data


def test_numbering_settings_can_update_and_void_with_reason(client, app):
    _login(client)

    updated = client.post(
        "/settings/numbering",
        data={
            "action": "update",
            "sequence_key": "sales_invoice",
            "prefix": "SI-{YYYY}-",
            "suffix": "",
            "starting_value": "1",
            "padding": "5",
            "reset_policy": "yearly",
        },
        follow_redirects=True,
    )
    assert updated.status_code == 200
    assert b"SI-2026-00001" in updated.data

    voided = client.post(
        "/settings/numbering",
        data={
            "action": "void_next",
            "sequence_key": "sales_invoice",
            "issue_date": date(2026, 9, 16).isoformat(),
            "reason": "Document cancelled before issue",
        },
        follow_redirects=True,
    )
    assert voided.status_code == 200
    assert b"SI-2026-00001" in voided.data
    assert b"Document cancelled before issue" in voided.data

    with app.app_context():
        allocation = NumberAllocation.query.filter_by(
            sequence_key="sales_invoice",
            formatted_number="SI-2026-00001",
        ).one()
        assert allocation.status == "void"
        assert allocation.reason == "Document cancelled before issue"


def test_numbering_management_api_uses_same_sequence_and_gap_controls(client, app):
    token = _full_access_token(app)
    headers = {"Authorization": f"Bearer {token}"}

    listing = client.get("/api/v1/settings/numbering", headers=headers)
    assert listing.status_code == 200
    rows = listing.get_json()["sequences"]
    invoice = next(row for row in rows if row["key"] == "sales_invoice")
    assert invoice["next_number"] == "INV-0001"

    updated = client.put(
        "/api/v1/settings/numbering/sales_invoice",
        headers=headers,
        json={
            "prefix": "API-{YY}-",
            "suffix": "",
            "starting_value": 1,
            "padding": 4,
            "reset_policy": "yearly",
        },
    )
    assert updated.status_code == 200
    assert updated.get_json()["sequence"]["next_number"] == "API-26-0001"

    voided = client.post(
        "/api/v1/settings/numbering/sales_invoice/void-next",
        headers=headers,
        json={
            "issue_date": "2026-09-16",
            "reason": "API controlled void test",
        },
    )
    assert voided.status_code == 201
    assert voided.get_json()["allocation"]["formatted_number"] == "API-26-0001"
    assert voided.get_json()["allocation"]["status"] == "void"

    detail = client.get(
        "/api/v1/settings/numbering/sales_invoice",
        headers=headers,
    )
    assert detail.status_code == 200
    payload = detail.get_json()
    assert payload["sequence"]["next_number"] == "API-26-0002"
    assert payload["gap_report"]["periods"][0]["void"] == ["API-26-0001"]
    assert payload["allocations"][0]["reason"] == "API controlled void test"
