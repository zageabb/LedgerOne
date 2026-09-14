from datetime import datetime, timedelta, timezone

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Membership, Organisation
from ledgerone.modules.settings.services import SettingsService
from ledgerone.services.context import AccessContext


def _system_context(app):
    with app.app_context():
        organisation = Organisation.query.one()
        return AccessContext.system(organisation.id)


def test_member_admin_creates_scoped_member_and_protects_last_owner(app):
    with app.app_context():
        organisation = Organisation.query.one()
        owner = Membership.query.filter_by(organisation_id=organisation.id, role="owner").one()
        context = AccessContext.system(organisation.id)

        member = SettingsService.save_member(
            context,
            email="reader@example.test",
            name="Reader",
            role="member",
            permissions=["ledger.read", "reports.read", "ledger.journals.post", "not.real"],
            password="temporary-123",
        )
        assert member.is_active is True
        assert member.role == "member"
        assert "ledger.read" in member.permissions
        assert "reports.read" in member.permissions
        assert "not.real" not in member.permissions

        try:
            SettingsService.save_member(
                context,
                email=owner.user.email,
                name=owner.user.name,
                role="member",
                permissions=["ledger.read"],
            )
            assert False, "last owner demotion should fail"
        except ValueError as exc:
            assert "at least one active owner" in str(exc)


def test_viewer_role_gets_read_only_catalog(app):
    with app.app_context():
        organisation = Organisation.query.one()
        context = AccessContext.system(organisation.id)
        membership = SettingsService.save_member(
            context,
            email="viewer@example.test",
            name="Viewer",
            role="viewer",
            permissions=["ledger.journals.post"],
            password="temporary-123",
        )
        assert "ledger.read" in membership.permissions
        assert "reports.read" in membership.permissions
        assert "ledger.journals.post" not in membership.permissions


def test_api_key_expiry_is_enforced(client, app):
    with app.app_context():
        organisation = Organisation.query.one()
        expired, expired_token = ApiKey.issue(
            name="expired",
            organisation_id=organisation.id,
            full_access=True,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.session.add(expired)
        db.session.commit()

    response = client.get(
        "/api/v1/ledger/accounts",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401


def test_rotating_api_key_revokes_old_token_and_preserves_scope(client, app):
    with app.app_context():
        organisation = Organisation.query.one()
        context = AccessContext.system(organisation.id)
        old, old_token = SettingsService.issue_api_key(
            context,
            name="reporting",
            full_access=False,
            permissions=["ledger.read"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        old_id = old.id
        new, new_token = SettingsService.rotate_api_key(context, old.id)
        assert new.id != old_id
        assert new.permissions == ["ledger.read"]
        assert new.full_access is False
        assert db.session.get(ApiKey, old_id).is_active is False

    denied = client.get(
        "/api/v1/ledger/accounts",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert denied.status_code == 401

    allowed = client.get(
        "/api/v1/ledger/accounts",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert allowed.status_code == 200


def test_settings_page_contains_team_and_key_lifecycle_controls(client, app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, _ = ApiKey.issue(
            name="UI rotation test",
            organisation_id=organisation.id,
            permissions=["ledger.read"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.session.add(key)
        db.session.commit()

    login = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert login.status_code == 200
    page = client.get("/settings/")
    assert page.status_code == 200
    assert b"Team access" in page.data
    assert b"Expires on" in page.data
    assert b"Rotate" in page.data
