from datetime import date

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, IdempotencyRecord, Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.settings.services import SettingsService
from ledgerone.services.context import AccessContext


def _setup(app):
    with app.app_context():
        organisation = Organisation.query.one()
        context = AccessContext.system(organisation.id)
        SettingsService.set_module_enabled(context, "workflows", False)
        key, token = ApiKey.issue(
            name="idempotency-test",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        return organisation.id, token, accounts


def _headers(token, key, **extra):
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": key,
    }
    headers.update(extra)
    return headers


def test_identical_journal_replay_returns_original_result_once(client, app):
    organisation_id, token, accounts = _setup(app)
    payload = {
        "date": "2026-10-03",
        "reference": "IDEMP-J-1",
        "description": "Idempotent journal",
        "lines": [
            {"account_id": accounts["1000"], "debit": "25.00", "credit": "0"},
            {"account_id": accounts["4000"], "debit": "0", "credit": "25.00"},
        ],
    }
    headers = _headers(token, "journal-001")

    first = client.post("/api/v1/ledger/journals", headers=headers, json=payload)
    second = client.post("/api/v1/ledger/journals", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.get_json() == first.get_json()

    with app.app_context():
        assert Journal.query.filter_by(organisation_id=organisation_id).count() == 1
        record = IdempotencyRecord.query.filter_by(
            organisation_id=organisation_id,
            idempotency_key="journal-001",
        ).one()
        assert record.status == "completed"
        assert record.response_status == 201
        assert record.result_entity_id == first.get_json()["id"]


def test_same_key_with_different_payload_is_conflict(client, app):
    _, token, accounts = _setup(app)
    headers = _headers(token, "journal-conflict")
    base = {
        "date": "2026-10-03",
        "description": "Original",
        "lines": [
            {"account_id": accounts["1000"], "debit": "10.00", "credit": "0"},
            {"account_id": accounts["4000"], "debit": "0", "credit": "10.00"},
        ],
    }
    assert client.post("/api/v1/ledger/journals", headers=headers, json=base).status_code == 201
    changed = {**base, "description": "Changed"}
    response = client.post("/api/v1/ledger/journals", headers=headers, json=changed)

    assert response.status_code == 409
    assert response.get_json()["error"] == "idempotency_conflict"


def test_invoice_and_bill_replays_do_not_duplicate_documents(client, app):
    _, token, accounts = _setup(app)
    with app.app_context():
        from ledgerone.modules.sales.services import SalesService
        from ledgerone.modules.purchases.services import PurchasesService

        context = AccessContext.system(Organisation.query.one().id)
        customer = SalesService.create_customer(context, name="Idempotent Customer")
        supplier = PurchasesService.create_supplier(context, name="Idempotent Supplier")
        customer_id = customer.id
        supplier_id = supplier.id

    invoice_payload = {
        "customer_id": customer_id,
        "invoice_date": "2026-10-03",
        "description": "API sale",
        "amount": "120.00",
        "receivable_account_id": accounts["1200"],
        "revenue_account_id": accounts["4000"],
        "currency": "GBP",
    }
    invoice_headers = _headers(token, "invoice-001")
    first_invoice = client.post("/api/v1/sales/invoices", headers=invoice_headers, json=invoice_payload)
    replay_invoice = client.post("/api/v1/sales/invoices", headers=invoice_headers, json=invoice_payload)
    assert first_invoice.status_code == 201
    assert replay_invoice.status_code == 201
    assert replay_invoice.get_json()["id"] == first_invoice.get_json()["id"]

    bill_payload = {
        "supplier_id": supplier_id,
        "bill_number": "SUP-1001",
        "bill_date": "2026-10-03",
        "description": "API purchase",
        "amount": "80.00",
        "payable_account_id": accounts["2100"],
        "expense_account_id": accounts["5000"],
        "currency": "GBP",
    }
    bill_headers = _headers(token, "bill-001")
    first_bill = client.post("/api/v1/purchases/bills", headers=bill_headers, json=bill_payload)
    replay_bill = client.post("/api/v1/purchases/bills", headers=bill_headers, json=bill_payload)
    assert first_bill.status_code == 201
    assert replay_bill.status_code == 201
    assert replay_bill.get_json()["id"] == first_bill.get_json()["id"]


def test_source_reference_pair_is_unique_per_operation(client, app):
    _, token, accounts = _setup(app)
    payload = {
        "date": "2026-10-03",
        "description": "Imported journal",
        "lines": [
            {"account_id": accounts["1000"], "debit": "5.00", "credit": "0"},
            {"account_id": accounts["4000"], "debit": "0", "credit": "5.00"},
        ],
    }
    source_headers = {
        "X-Source-System": "erp-a",
        "X-Source-Reference": "TX-44",
    }
    first = client.post(
        "/api/v1/ledger/journals",
        headers=_headers(token, "source-key-1", **source_headers),
        json=payload,
    )
    second = client.post(
        "/api/v1/ledger/journals",
        headers=_headers(token, "source-key-2", **source_headers),
        json=payload,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.get_json() == first.get_json()
