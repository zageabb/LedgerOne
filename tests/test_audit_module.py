from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.settings.services import SettingsService
from ledgerone.services.context import AccessContext


def _key(app, *, full_access=False, permissions=None):
    with app.app_context():
        organisation = Organisation.query.one()
        # This suite verifies audit events emitted by completed accounting writes. The
        # workflow boundary has separate tests, so make the direct-post fixture explicit.
        SettingsService.set_module_enabled(
            AccessContext.system(organisation.id),
            "workflows",
            False,
        )
        key, token = ApiKey.issue(
            name="audit-test",
            organisation_id=organisation.id,
            full_access=full_access,
            permissions=list(permissions or []),
        )
        db.session.add(key)
        db.session.commit()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        return token, accounts


def test_audit_api_records_and_filters_posted_journal(client, app):
    token, accounts = _key(app, full_access=True)
    headers = {"Authorization": f"Bearer {token}"}
    posted = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-09-14",
            "reference": "AUD-001",
            "description": "Audit test journal",
            "lines": [
                {"account_id": accounts["1000"], "debit": "42.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "42.00"},
            ],
        },
    )
    assert posted.status_code == 201

    response = client.get(
        "/api/v1/audit?action=journal_posted&module_id=ledger",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] >= 1
    event = payload["events"][0]
    assert event["module_id"] == "ledger"
    assert event["action"] == "journal_posted"
    assert event["detail"]["reference"] == "AUD-001"
    assert event["detail"]["total_debit"] == "42.00"


def test_business_module_writes_are_visible_in_audit_trail(client, app):
    token, _ = _key(app, full_access=True)
    headers = {"Authorization": f"Bearer {token}"}

    customer = client.post(
        "/api/v1/sales/customers",
        headers=headers,
        json={"name": "Audit Customer", "email": "audit@example.test"},
    )
    assert customer.status_code == 201

    supplier = client.post(
        "/api/v1/purchases/suppliers",
        headers=headers,
        json={"name": "Audit Supplier"},
    )
    assert supplier.status_code == 201

    sales_events = client.get(
        "/api/v1/audit?module_id=sales&action=customer_created",
        headers=headers,
    ).get_json()["events"]
    purchase_events = client.get(
        "/api/v1/audit?module_id=purchases&action=supplier_created",
        headers=headers,
    ).get_json()["events"]

    assert any(event["entity_id"] == customer.get_json()["id"] for event in sales_events)
    assert any(event["entity_id"] == supplier.get_json()["id"] for event in purchase_events)


def test_audit_export_requires_export_permission(client, app):
    reader_token, _ = _key(app, permissions={"audit.read"})
    reader_headers = {"Authorization": f"Bearer {reader_token}"}

    listing = client.get("/api/v1/audit", headers=reader_headers)
    assert listing.status_code == 200

    denied = client.get("/api/v1/audit/export", headers=reader_headers)
    assert denied.status_code == 403


def test_full_access_audit_csv_export_contains_events(client, app):
    token, accounts = _key(app, full_access=True)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-09-14",
            "reference": "CSV-001",
            "description": "CSV audit journal",
            "lines": [
                {"account_id": accounts["1000"], "debit": "5.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "5.00"},
            ],
        },
    )

    response = client.get(
        "/api/v1/audit/export?action=journal_posted",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    text = response.get_data(as_text=True)
    assert "created_at,module,action" in text
    assert "journal_posted" in text
    assert "CSV-001" in text


def test_audit_browser_page_renders_for_owner(client):
    login = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert login.status_code == 200
    response = client.get("/audit/")
    assert response.status_code == 200
    assert b"Activity" in response.data or b"Audit Trail" in response.data
