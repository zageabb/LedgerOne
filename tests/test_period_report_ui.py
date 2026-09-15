from datetime import date

from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


def _seed(app):
    with app.app_context():
        organisation = Organisation.query.one()
        accounts = {
            row.code: row
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        context = AccessContext.system(organisation.id)
        LedgerService.post_journal(
            context,
            journal_date=date(2025, 12, 31),
            description="Opening comparative income",
            reference="UI-PRIOR",
            source_module="ledger",
            lines=[
                {"account_id": accounts["1000"].id, "debit": "40.00", "credit": 0},
                {"account_id": accounts["4000"].id, "debit": 0, "credit": "40.00"},
            ],
        )
        LedgerService.post_journal(
            context,
            journal_date=date(2026, 3, 1),
            description="Current income",
            reference="UI-CURRENT",
            source_module="ledger",
            lines=[
                {"account_id": accounts["1000"].id, "debit": "75.00", "credit": 0},
                {"account_id": accounts["4000"].id, "debit": 0, "credit": "75.00"},
            ],
        )
        return accounts["1000"].id


def test_period_report_pages_render_with_date_controls(client, app):
    bank_id = _seed(app)
    login = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert login.status_code == 200

    reports = client.get(
        "/reports/?from_date=2026-01-01&to_date=2026-12-31&compare=1"
    )
    assert reports.status_code == 200
    assert b"Profit &amp; loss" in reports.data
    assert b"Current / unclosed earnings" in reports.data
    assert b"2026-01-01" in reports.data
    assert b"2026-12-31" in reports.data
    assert b"/reports/trial-balance" in reports.data

    trial_balance = client.get(
        "/reports/trial-balance?from_date=2026-01-01&as_of=2026-12-31"
    )
    assert trial_balance.status_code == 200
    assert b"Posted movement" in trial_balance.data
    assert b"2026-01-01" in trial_balance.data

    general_ledger = client.get(
        f"/reports/general-ledger?from_date=2026-01-01&to_date=2026-12-31&account_id={bank_id}"
    )
    assert general_ledger.status_code == 200
    assert b"Brought forward" in general_ledger.data
    assert b"Carried forward" in general_ledger.data
    assert b"UI-CURRENT" in general_ledger.data
