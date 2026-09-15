import io
from pathlib import Path

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.documents.models import SourceDocument
from ledgerone.modules.settings.services import SettingsService
from ledgerone.services.context import AccessContext


def _full_key(app):
    with app.app_context():
        organisation = Organisation.query.one()
        # Document tests need an already-posted entity to attach evidence to. Workflow
        # proposal routing is covered by its own API boundary suite.
        SettingsService.set_module_enabled(
            AccessContext.system(organisation.id),
            "workflows",
            False,
        )
        key, token = ApiKey.issue(
            name="documents-test",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        return token


def _journal(client, app, token):
    with app.app_context():
        organisation = Organisation.query.one()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
    response = client.post(
        "/api/v1/ledger/journals",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "date": "2026-09-14",
            "reference": "DOC-001",
            "description": "Document target",
            "lines": [
                {"account_id": accounts["1000"], "debit": "10.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "10.00"},
            ],
        },
    )
    assert response.status_code == 201
    return response.get_json()["id"]


def test_upload_list_and_download_source_document(client, app):
    token = _full_key(app)
    journal_id = _journal(client, app, token)
    headers = {"Authorization": f"Bearer {token}"}

    uploaded = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={
            "entity_type": "journal",
            "entity_id": journal_id,
            "title": "Receipt",
            "file": (io.BytesIO(b"ledgerone evidence"), "receipt.txt"),
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    payload = uploaded.get_json()
    assert payload["title"] == "Receipt"
    assert payload["kind"] == "file"
    assert payload["sha256"]
    document_id = payload["id"]

    listing = client.get(
        f"/api/v1/documents?entity_type=journal&entity_id={journal_id}",
        headers=headers,
    )
    assert listing.status_code == 200
    assert [row["id"] for row in listing.get_json()["documents"]] == [document_id]

    content = client.get(f"/api/v1/documents/{document_id}/content", headers=headers)
    assert content.status_code == 200
    assert content.data == b"ledgerone evidence"

    with app.app_context():
        row = db.session.get(SourceDocument, document_id)
        stored = Path(app.config["DOCUMENT_STORAGE_DIR"]) / row.storage_key
        assert stored.read_bytes() == b"ledgerone evidence"


def test_external_source_reference_is_stored(client, app):
    token = _full_key(app)
    journal_id = _journal(client, app, token)
    response = client.post(
        "/api/v1/documents/reference",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "entity_type": "journal",
            "entity_id": journal_id,
            "title": "Supplier portal",
            "reference_url": "https://example.test/evidence/123",
        },
    )
    assert response.status_code == 201
    assert response.get_json()["kind"] == "reference"
    assert response.get_json()["reference_url"] == "https://example.test/evidence/123"


def test_cannot_attach_document_to_foreign_organisation_record(client, app):
    token = _full_key(app)
    with app.app_context():
        other = Organisation(name="Other", slug="documents-other")
        db.session.add(other)
        db.session.flush()
        foreign = Journal(
            organisation_id=other.id,
            journal_date=__import__("datetime").date(2026, 9, 14),
            description="Foreign journal",
            status="posted",
            source_module="ledger",
        )
        db.session.add(foreign)
        db.session.commit()
        foreign_id = foreign.id

    response = client.post(
        "/api/v1/documents/reference",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "entity_type": "journal",
            "entity_id": foreign_id,
            "reference_url": "https://example.test/nope",
        },
    )
    assert response.status_code == 400
    assert "not found in this organisation" in response.get_json()["error"]
