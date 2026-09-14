from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.banking.models import BankTransaction


def _setup(app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="bank-reconcile-test",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        db.session.commit()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        return token, accounts


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _create_bank_and_transaction(client, token, accounts, *, amount, tx_date="2026-09-14", description="Bank item"):
    headers = _headers(token)
    bank = client.post(
        "/api/v1/banking/accounts",
        headers=headers,
        json={
            "name": "Main Bank",
            "institution": "Test Bank",
            "currency": "GBP",
            "ledger_account_id": accounts["1000"],
        },
    )
    assert bank.status_code == 201
    transaction = client.post(
        "/api/v1/banking/transactions",
        headers=headers,
        json={
            "bank_account_id": bank.get_json()["id"],
            "date": tx_date,
            "description": description,
            "amount": str(amount),
        },
    )
    assert transaction.status_code == 201
    return transaction.get_json()["id"]


def test_existing_journal_can_be_found_matched_and_unmatched(client, app):
    token, accounts = _setup(app)
    headers = _headers(token)
    transaction_id = _create_bank_and_transaction(
        client,
        token,
        accounts,
        amount="100.00",
        description="Customer receipt",
    )

    posted = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-09-13",
            "reference": "REC-100",
            "description": "Customer receipt",
            "lines": [
                {"account_id": accounts["1000"], "debit": "100.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "100.00"},
            ],
        },
    )
    assert posted.status_code == 201
    journal_id = posted.get_json()["id"]

    candidates = client.get(
        f"/api/v1/banking/transactions/{transaction_id}/candidates",
        headers=headers,
    )
    assert candidates.status_code == 200
    assert journal_id in {row["id"] for row in candidates.get_json()["candidates"]}

    matched = client.post(
        f"/api/v1/banking/transactions/{transaction_id}/match",
        headers=headers,
        json={"journal_id": journal_id},
    )
    assert matched.status_code == 200
    assert matched.get_json()["status"] == "reconciled"
    assert matched.get_json()["matched_journal_id"] == journal_id

    unmatched = client.post(
        f"/api/v1/banking/transactions/{transaction_id}/unmatch",
        headers=headers,
    )
    assert unmatched.status_code == 200
    assert unmatched.get_json()["status"] == "unreconciled"
    assert unmatched.get_json()["matched_journal_id"] is None


def test_post_and_match_outgoing_transaction_creates_balanced_journal(client, app):
    token, accounts = _setup(app)
    headers = _headers(token)
    transaction_id = _create_bank_and_transaction(
        client,
        token,
        accounts,
        amount="-75.00",
        description="Office costs",
    )

    response = client.post(
        f"/api/v1/banking/transactions/{transaction_id}/post-and-match",
        headers=headers,
        json={
            "offset_account_id": accounts["5000"],
            "reference": "BANK-OFFICE",
            "description": "Office costs",
        },
    )
    assert response.status_code == 201
    result = response.get_json()
    assert result["status"] == "reconciled"

    with app.app_context():
        transaction = db.session.get(BankTransaction, transaction_id)
        journal = db.session.get(Journal, result["journal_id"])
        assert transaction.matched_journal_id == journal.id
        assert journal.source_module == "banking"
        assert journal.source_reference == transaction_id
        assert journal.total_debit == Decimal("75.00")
        assert journal.total_credit == Decimal("75.00")
        by_account = {
            line.account_id: (line.debit, line.credit)
            for line in journal.lines
        }
        assert by_account[accounts["5000"]] == (Decimal("75.00"), Decimal("0.00"))
        assert by_account[accounts["1000"]] == (Decimal("0.00"), Decimal("75.00"))

    trial = client.get("/api/v1/ledger/trial-balance", headers=headers)
    rows = {row["code"]: row for row in trial.get_json()["rows"]}
    assert rows["5000"]["balance"] == "75.00"
    assert rows["1000"]["balance"] == "-75.00"

    unmatch = client.post(
        f"/api/v1/banking/transactions/{transaction_id}/unmatch",
        headers=headers,
    )
    assert unmatch.status_code == 400
    assert "Reverse that journal" in unmatch.get_json()["error"]


def test_same_journal_cannot_be_matched_twice(client, app):
    token, accounts = _setup(app)
    headers = _headers(token)
    first_tx = _create_bank_and_transaction(client, token, accounts, amount="30.00")

    # Reuse the same bank account for a second transaction.
    bank_transactions = client.get("/api/v1/banking/transactions", headers=headers).get_json()["transactions"]
    bank_account_id = bank_transactions[0]["bank_account_id"]
    second = client.post(
        "/api/v1/banking/transactions",
        headers=headers,
        json={
            "bank_account_id": bank_account_id,
            "date": "2026-09-14",
            "description": "Second receipt",
            "amount": "30.00",
        },
    )
    second_tx = second.get_json()["id"]

    journal = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-09-14",
            "description": "One receipt journal",
            "lines": [
                {"account_id": accounts["1000"], "debit": "30.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "30.00"},
            ],
        },
    ).get_json()["id"]

    first = client.post(
        f"/api/v1/banking/transactions/{first_tx}/match",
        headers=headers,
        json={"journal_id": journal},
    )
    assert first.status_code == 200

    second_match = client.post(
        f"/api/v1/banking/transactions/{second_tx}/match",
        headers=headers,
        json={"journal_id": journal},
    )
    assert second_match.status_code == 400
    assert "already matched" in second_match.get_json()["error"]


def test_post_and_match_respects_locked_period_atomically(client, app):
    token, accounts = _setup(app)
    headers = _headers(token)
    transaction_id = _create_bank_and_transaction(
        client,
        token,
        accounts,
        amount="-25.00",
        tx_date="2026-08-20",
        description="Locked payment",
    )

    period = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={"name": "August 2026", "start_date": "2026-08-01", "end_date": "2026-08-31"},
    )
    period_id = period.get_json()["id"]
    client.post(
        f"/api/v1/ledger/periods/{period_id}/lock",
        headers=headers,
        json={"locked": True},
    )

    response = client.post(
        f"/api/v1/banking/transactions/{transaction_id}/post-and-match",
        headers=headers,
        json={"offset_account_id": accounts["5000"]},
    )
    assert response.status_code == 400
    assert "locked period" in response.get_json()["error"]

    with app.app_context():
        transaction = db.session.get(BankTransaction, transaction_id)
        assert transaction.status == "unreconciled"
        assert transaction.matched_journal_id is None
        assert Journal.query.count() == 0
