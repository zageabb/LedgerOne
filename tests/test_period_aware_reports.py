from datetime import date

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account
from ledgerone.modules.reports.services import ReportsService
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


def _setup():
    organisation = Organisation.query.one()
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    return organisation, accounts, AccessContext.system(organisation.id)


def _post(context, *, journal_date, amount, debit_account, credit_account, reference):
    return LedgerService.post_journal(
        context,
        journal_date=journal_date,
        description=reference,
        reference=reference,
        source_module="ledger",
        lines=[
            {"account_id": debit_account.id, "debit": amount, "credit": 0},
            {"account_id": credit_account.id, "debit": 0, "credit": amount},
        ],
    )


def _seed_timeline(context, accounts):
    _post(
        context,
        journal_date=date(2025, 1, 10),
        amount="100.00",
        debit_account=accounts["1000"],
        credit_account=accounts["4000"],
        reference="PRIOR-INCOME",
    )
    _post(
        context,
        journal_date=date(2026, 1, 15),
        amount="200.00",
        debit_account=accounts["1000"],
        credit_account=accounts["4000"],
        reference="PERIOD-INCOME",
    )
    _post(
        context,
        journal_date=date(2026, 2, 15),
        amount="50.00",
        debit_account=accounts["5000"],
        credit_account=accounts["1000"],
        reference="PERIOD-EXPENSE",
    )


def test_profit_and_loss_uses_only_requested_period(app):
    with app.app_context():
        _, accounts, context = _setup()
        _seed_timeline(context, accounts)
        _post(
            context,
            journal_date=date(2027, 1, 15),
            amount="300.00",
            debit_account=accounts["1000"],
            credit_account=accounts["4000"],
            reference="FUTURE-INCOME",
        )

        report = ReportsService.profit_and_loss(
            context,
            from_date=date(2026, 1, 1),
            to_date=date(2026, 12, 31),
        )
        assert report["total_income"] == 200
        assert report["total_expenses"] == 50
        assert report["net_profit"] == 150


def test_balance_sheet_as_of_excludes_later_transactions_and_includes_current_earnings(app):
    with app.app_context():
        _, accounts, context = _setup()
        _seed_timeline(context, accounts)
        before_future = ReportsService.balance_sheet(
            context,
            as_of=date(2026, 12, 31),
        )
        assert before_future["total_assets"] == 250
        assert before_future["current_earnings"] == 250
        assert before_future["total_equity"] == 250
        assert before_future["balance_check"] == 0

        _post(
            context,
            journal_date=date(2027, 1, 15),
            amount="300.00",
            debit_account=accounts["1000"],
            credit_account=accounts["4000"],
            reference="FUTURE-INCOME",
        )
        after_future = ReportsService.balance_sheet(
            context,
            as_of=date(2026, 12, 31),
        )
        assert after_future["total_assets"] == before_future["total_assets"]
        assert after_future["current_earnings"] == before_future["current_earnings"]
        assert after_future["balance_check"] == 0


def test_trial_balance_is_balanced_at_multiple_dates_and_can_show_period_movement(app):
    with app.app_context():
        _, accounts, context = _setup()
        _seed_timeline(context, accounts)

        prior = ReportsService.trial_balance(context, as_of=date(2025, 12, 31))
        current = ReportsService.trial_balance(context, as_of=date(2026, 12, 31))
        movement = ReportsService.trial_balance(
            context,
            from_date=date(2026, 1, 1),
            as_of=date(2026, 12, 31),
        )

        assert prior["total_debit"] == prior["total_credit"] == 100
        assert current["total_debit"] == current["total_credit"] == 350
        assert movement["mode"] == "movement"
        assert movement["total_debit"] == movement["total_credit"] == 250
        assert movement["difference"] == 0


def test_general_ledger_has_brought_forward_movement_and_carried_forward(app):
    with app.app_context():
        _, accounts, context = _setup()
        _seed_timeline(context, accounts)

        report = ReportsService.general_ledger(
            context,
            from_date=date(2026, 1, 1),
            to_date=date(2026, 12, 31),
            account_id=accounts["1000"].id,
        )
        row = report["accounts"][0]
        assert row["opening_balance"] == 100
        assert row["movement_debit"] == 200
        assert row["movement_credit"] == 50
        assert row["closing_balance"] == 250
        assert [entry["reference"] for entry in row["entries"]] == [
            "PERIOD-INCOME",
            "PERIOD-EXPENSE",
        ]
        assert row["entries"][-1]["running_balance"] == 250


def test_prior_year_comparative_is_stable_after_later_posting(app):
    with app.app_context():
        _, accounts, context = _setup()
        _seed_timeline(context, accounts)
        report_before = ReportsService.profit_and_loss(
            context,
            from_date=date(2026, 1, 1),
            to_date=date(2026, 12, 31),
            compare_from=date(2025, 1, 1),
            compare_to=date(2025, 12, 31),
        )
        assert report_before["net_profit"] == 150
        assert report_before["comparative"]["net_profit"] == 100

        _post(
            context,
            journal_date=date(2027, 1, 15),
            amount="300.00",
            debit_account=accounts["1000"],
            credit_account=accounts["4000"],
            reference="FUTURE-INCOME",
        )
        report_after = ReportsService.profit_and_loss(
            context,
            from_date=date(2026, 1, 1),
            to_date=date(2026, 12, 31),
            compare_from=date(2025, 1, 1),
            compare_to=date(2025, 12, 31),
        )
        assert report_after["net_profit"] == report_before["net_profit"]
        assert report_after["comparative"]["net_profit"] == report_before["comparative"]["net_profit"]


def test_report_api_uses_same_date_aware_services(app, client):
    with app.app_context():
        organisation, accounts, context = _setup()
        _seed_timeline(context, accounts)
        key, token = ApiKey.issue(
            name="period-report-api",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        bank_id = accounts["1000"].id

    headers = {"Authorization": f"Bearer {token}"}
    pnl = client.get(
        "/api/v1/reports/profit-loss?from_date=2026-01-01&to_date=2026-12-31&compare_from=2025-01-01&compare_to=2025-12-31",
        headers=headers,
    )
    assert pnl.status_code == 200
    assert pnl.get_json()["net_profit"] == "150.00"
    assert pnl.get_json()["comparative"]["net_profit"] == "100.00"

    balance_sheet = client.get(
        "/api/v1/reports/balance-sheet?as_of=2026-12-31",
        headers=headers,
    )
    assert balance_sheet.status_code == 200
    assert balance_sheet.get_json()["as_of"] == "2026-12-31"
    assert balance_sheet.get_json()["current_earnings"] == "250.00"

    trial_balance = client.get(
        "/api/v1/reports/trial-balance?from_date=2026-01-01&as_of=2026-12-31",
        headers=headers,
    )
    assert trial_balance.status_code == 200
    assert trial_balance.get_json()["mode"] == "movement"
    assert trial_balance.get_json()["difference"] == "0.00"

    general_ledger = client.get(
        f"/api/v1/reports/general-ledger?from_date=2026-01-01&to_date=2026-12-31&account_id={bank_id}",
        headers=headers,
    )
    assert general_ledger.status_code == 200
    assert general_ledger.get_json()["accounts"][0]["opening_balance"] == "100.00"
    assert general_ledger.get_json()["accounts"][0]["closing_balance"] == "250.00"
