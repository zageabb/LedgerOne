from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, RecurringJournal
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService
from ledgerone.services.period_policy import PeriodPolicyError, PeriodPolicyService


def _setup():
    organisation = Organisation.query.one()
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, accounts, AccessContext.system(organisation.id)


def _lines(accounts, amount="10.00"):
    return [
        {"account_id": accounts["1000"].id, "debit": amount, "credit": "0"},
        {"account_id": accounts["4000"].id, "debit": "0", "credit": amount},
    ]


def test_required_policy_rejects_undefined_period_and_open_period_allows_posting(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        PeriodPolicyService.set_policy(context, mode="required")

        with pytest.raises(PeriodPolicyError, match="not inside a defined accounting period"):
            LedgerService.post_journal(
                context,
                journal_date=date(2026, 9, 15),
                description="Undefined period",
                lines=_lines(accounts),
            )
        db.session.rollback()

        LedgerService.create_period(
            context,
            name="September 2026",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
        journal = LedgerService.post_journal(
            context,
            journal_date=date(2026, 9, 15),
            description="Open period",
            lines=_lines(accounts),
        )
        assert journal.status == "posted"


def test_soft_close_requires_override_permission_and_reason_and_is_audited(app):
    with app.app_context():
        organisation, accounts, admin = _setup()
        PeriodPolicyService.set_policy(admin, mode="required")
        period = LedgerService.create_period(
            admin,
            name="September 2026",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
        PeriodPolicyService.set_period_status(admin, period.id, status="soft_closed")

        ordinary = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="ordinary-user",
            permissions=frozenset({"ledger.journals.post"}),
        )
        with pytest.raises(PeriodPolicyError, match="override permission is required"):
            LedgerService.post_journal(
                ordinary,
                journal_date=date(2026, 9, 15),
                description="No override permission",
                lines=_lines(accounts),
                period_override_reason="Late adjustment",
            )
        db.session.rollback()

        override_user = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="override-user",
            permissions=frozenset({"ledger.journals.post", "ledger.periods.override"}),
        )
        with pytest.raises(PeriodPolicyError, match="override reason is required"):
            LedgerService.post_journal(
                override_user,
                journal_date=date(2026, 9, 15),
                description="Missing override reason",
                lines=_lines(accounts),
            )
        db.session.rollback()

        journal = LedgerService.post_journal(
            override_user,
            journal_date=date(2026, 9, 15),
            description="Approved late adjustment",
            lines=_lines(accounts),
            period_override_reason="Approved month-end adjustment",
        )
        assert journal.status == "posted"
        event = AuditEvent.query.filter_by(
            organisation_id=organisation.id,
            action="soft_closed_period_override",
            entity_id=period.id,
        ).order_by(AuditEvent.created_at.desc()).first()
        assert event is not None
        assert event.actor_id == "override-user"
        assert event.detail["reason"] == "Approved month-end adjustment"


def test_hard_closed_period_rejects_even_override_and_reopen_requires_reason(app):
    with app.app_context():
        organisation, accounts, admin = _setup()
        PeriodPolicyService.set_policy(admin, mode="required")
        period = LedgerService.create_period(
            admin,
            name="September 2026",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
        PeriodPolicyService.set_period_status(admin, period.id, status="hard_closed")

        with pytest.raises(PeriodPolicyError, match="locked period"):
            LedgerService.post_journal(
                admin,
                journal_date=date(2026, 9, 15),
                description="Hard-close bypass attempt",
                lines=_lines(accounts),
                period_override_reason="Should never bypass hard close",
            )
        db.session.rollback()

        with pytest.raises(PeriodPolicyError, match="requires a reason"):
            PeriodPolicyService.set_period_status(admin, period.id, status="open")
        db.session.rollback()

        reopened = PeriodPolicyService.set_period_status(
            admin,
            period.id,
            status="open",
            reason="Correction window approved",
        )
        assert reopened.status == "open"
        event = AuditEvent.query.filter_by(
            organisation_id=organisation.id,
            action="period_reopened",
            entity_id=period.id,
        ).order_by(AuditEvent.created_at.desc()).first()
        assert event is not None
        assert event.detail["reason"] == "Correction window approved"
        assert event.created_at is not None


def test_recurring_and_sales_use_same_required_period_policy(app):
    with app.app_context():
        organisation, accounts, context = _setup()
        PeriodPolicyService.set_policy(context, mode="required")

        customer = SalesService.create_customer(context, name="Period Policy Customer")
        with pytest.raises(PeriodPolicyError, match="not inside a defined accounting period"):
            SalesService.create_invoice(
                context,
                customer_id=customer.id,
                invoice_number="PERIOD-001",
                invoice_date=date(2026, 9, 15),
                due_date=None,
                description="Services",
                amount="25.00",
                receivable_account_id=accounts["1200"].id,
                revenue_account_id=accounts["4000"].id,
                currency="GBP",
            )
        db.session.rollback()
        assert SalesInvoice.query.count() == 0

        schedule = LedgerService.create_recurring_journal(
            context,
            name="Undefined-period recurring",
            description="Recurring income",
            frequency="monthly",
            next_run_date=date(2026, 10, 15),
            lines=_lines(accounts, "15.00"),
        )
        with pytest.raises(PeriodPolicyError, match="not inside a defined accounting period"):
            LedgerService.run_recurring_journal(context, schedule.id)
        db.session.rollback()
        schedule = db.session.get(RecurringJournal, schedule.id)
        assert schedule.run_count == 0
        assert schedule.next_run_date == date(2026, 10, 15)


def test_period_policy_api_supports_required_and_status_transitions(client, app):
    with app.app_context():
        organisation, _, context = _setup()
        from ledgerone.models.core import ApiKey

        key, token = ApiKey.issue(
            name="period-policy-test",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
    headers = {"Authorization": f"Bearer {token}"}

    policy = client.put(
        "/api/v1/ledger/period-policy",
        headers=headers,
        json={"mode": "required"},
    )
    assert policy.status_code == 200
    assert policy.get_json()["mode"] == "required"

    created = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={
            "name": "September 2026",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
        },
    )
    assert created.status_code == 201
    period_id = created.get_json()["id"]

    soft = client.post(
        f"/api/v1/ledger/periods/{period_id}/status",
        headers=headers,
        json={"status": "soft_closed", "reason": "Month-end review"},
    )
    assert soft.status_code == 200
    assert soft.get_json()["status"] == "soft_closed"

    missing_reason = client.post(
        f"/api/v1/ledger/periods/{period_id}/status",
        headers=headers,
        json={"status": "open"},
    )
    assert missing_reason.status_code == 400

    reopened = client.post(
        f"/api/v1/ledger/periods/{period_id}/status",
        headers=headers,
        json={"status": "open", "reason": "Approved reopen"},
    )
    assert reopened.status_code == 200
    assert reopened.get_json()["status"] == "open"
