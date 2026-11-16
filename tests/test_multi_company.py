"""Regression coverage for LedgerOne's independent company ledgers."""
import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.security import browser_context
from ledgerone.services.company import CompanyService
from ledgerone.services.context import AccessContext


def _owner(app):
    with app.app_context():
        user = User.query.filter_by(email="test-admin@ledgerone.local").one()
        membership = Membership.query.filter_by(user_id=user.id).one()
        return user.id, membership.organisation_id


def test_company_creation_initialises_distinct_chart_and_owner(app):
    user_id, org_id = _owner(app)
    with app.app_context():
        ctx = AccessContext(identity_type="user", user_id=user_id,
                            organisation_id=org_id, full_access=True)
        new = CompanyService.create(ctx, name="Second Trading Company", company_code="SECOND")
        assert new.id != org_id
        assert new.company_code == "SECOND"
        assert Membership.query.filter_by(organisation_id=new.id, user_id=user_id,
                                          role="owner", is_active=True).count() == 1
        first_accounts = Account.query.filter_by(organisation_id=org_id).all()
        second_accounts = Account.query.filter_by(organisation_id=new.id).all()
        assert first_accounts and second_accounts
        assert {a.id for a in first_accounts}.isdisjoint({a.id for a in second_accounts})
        assert {a.code for a in first_accounts} == {a.code for a in second_accounts}
        assert Journal.query.filter_by(organisation_id=new.id).count() == 0


def test_company_profile_code_validation_and_isolation(app):
    user_id, org_id = _owner(app)
    with app.app_context():
        ctx = AccessContext(identity_type="user", user_id=user_id,
                            organisation_id=org_id, full_access=True)
        CompanyService.update(ctx, company_code="FIRST", trading_name="First",
                              registered_address={"city": "Stafford"})
        second = CompanyService.create(ctx, name="Second", company_code="SECOND")
        assert second.company_code == "SECOND"
        with pytest.raises(ValueError, match="already allocated"):
            CompanyService.update(ctx, company_code="SECOND")
        with pytest.raises(PermissionError):
            CompanyService.create(AccessContext(identity_type="user", user_id=user_id,
                                  organisation_id=org_id, permissions=frozenset()),
                                  name="Not permitted", company_code="NO")
        assert Organisation.query.filter_by(id=org_id).one().company_code == "FIRST"


def test_multi_company_login_requires_selection_and_switch(client, app):
    user_id, org_id = _owner(app)
    with app.app_context():
        owner = AccessContext(identity_type="user", user_id=user_id,
                              organisation_id=org_id, full_access=True)
        company_id = CompanyService.create(owner, name="Second Co", company_code="SECOND").id
    response = client.post("/auth/login", data={
        "email": "test-admin@ledgerone.local", "password": "test-password"
    }, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/companies")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/companies")
    response = client.post("/auth/organisation", data={"organisation_id": company_id})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert sess["organisation_id"] == company_id
    with app.app_context():
        membership = Membership.query.filter_by(user_id=user_id, organisation_id=company_id).one()
        membership.is_active = False
        db.session.commit()
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/companies")
    with client.session_transaction() as sess:
        assert sess.get("organisation_id") != company_id


def test_company_switch_rejects_non_member(client, app):
    user_id, org_id = _owner(app)
    with app.app_context():
        other = Organisation(name="Unrelated company", slug="unrelated-company",
                             company_code="OTHER")
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    client.post("/auth/login", data={
        "email": "test-admin@ledgerone.local", "password": "test-password"
    })
    assert client.post("/auth/organisation", data={"organisation_id": other_id}).status_code == 404
    with client.session_transaction() as sess:
        assert sess.get("organisation_id") == org_id


def test_company_specific_roles_do_not_inherit(app):
    user_id, org_id = _owner(app)
    with app.app_context():
        owner = AccessContext(identity_type="user", user_id=user_id,
                              organisation_id=org_id, full_access=True)
        second = CompanyService.create(owner, name="Second Co", company_code="SECOND")
        member = Membership.query.filter_by(organisation_id=second.id, user_id=user_id).one()
        member.role = "viewer"
        member.permissions = ["ledger.read"]
        db.session.commit()
        assert Membership.query.filter_by(organisation_id=org_id, user_id=user_id).one().role == "owner"
        assert member.role == "viewer"
