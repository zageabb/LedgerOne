from ledgerone.extensions import db
from ledgerone.models.core import ModuleState, Organisation, User
from ledgerone.models.ledger import Account


def test_bootstrap_creates_admin_organisation_and_chart(app):
    with app.app_context():
        assert User.query.count() == 1
        assert Organisation.query.count() == 1
        organisation = Organisation.query.one()
        assert organisation.name == "Test Ledger"
        assert Account.query.filter_by(organisation_id=organisation.id).count() >= 12
        assert Account.query.filter_by(organisation_id=organisation.id, code="1000").one().name == "Current Account"
        assert ModuleState.query.filter_by(organisation_id=organisation.id).count() >= 1


def test_login_dashboard_and_ui_mode_toggle(client, app):
    response = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"LedgerOne" in response.data

    response = client.post("/auth/ui-mode", data={"mode": "professional"}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        user = User.query.filter_by(email="test-admin@ledgerone.local").one()
        assert user.ui_mode == "professional"


def test_invalid_login_does_not_authenticate(client):
    response = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "wrong"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Email or password was not recognised" in response.data

    protected = client.get("/", follow_redirects=False)
    assert protected.status_code in {302, 401}
