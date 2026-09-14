from __future__ import annotations

import pytest

from ledgerone import create_app
from ledgerone.extensions import db


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / "ledgerone-test.db"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "ledgerone-test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "AUTO_CREATE_SCHEMA": True,
            "AUTO_SEED_DEFAULTS": True,
            "WTF_CSRF_ENABLED": False,
            "LOCAL_AI_ENABLED": False,
            "LOCAL_AI_ALLOW_WRITES": False,
            "ADMIN_EMAIL": "test-admin@ledgerone.local",
            "ADMIN_PASSWORD": "test-password",
            "ADMIN_NAME": "LedgerOne Test Admin",
            "DEFAULT_ORG_NAME": "Test Ledger",
        }
    )

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()
