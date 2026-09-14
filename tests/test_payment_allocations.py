from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.sales.models import SalesInvoice


def _setup(app):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="payment-allocation-test",
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


def test_customer_partial_payment_then_bank_journal_adoption_settles_invoice(client, app):
    token, accounts = _setup(app)
    headers = _headers(token)

    customer = client.post(
        "/api/v1/sales/customers",
        headers=headers,
        json={"name": "Settlement Customer"},
    ).get_json()["id"]
    invoice_response = client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer,
            "invoice_number": "INV-PAY-001",
            "invoice_date": "2026-09-14",
            "amount": "100.00",
            "receivable_account_id": accounts["1200"],
            "revenue_account_id": accounts["4000"],
            "description": "Services",
        },
    )
    assert invoice_response.status_code == 201
    invoice_id = invoice_response.get_json()["id"]

    payment = client.post(
        "/api/v1/sales/payments",
        headers=headers,
        json={
            "customer_id": customer,
            "date": "2026-09-14",
            "amount": "60.00",
            "bank_account_id": accounts["1000"],
            "receivable_account_id": accounts["1200"],
            "reference": "PART-60",
        },
    )
    assert payment.status_code == 201
    payment_id = payment.get_json()["id"]

    allocated = client.post(
        f"/api/v1/sales/payments/{payment_id}/allocate",
        headers=headers,
        json={"allocations": [{"invoice_id": invoice_id, "amount": "60.00"}]},
    )
    assert allocated.status_code == 200
    assert allocated.get_json()["status"] == "allocated"

    invoices = client.get("/api/v1/sales/invoices", headers=headers).get_json()["invoices"]
    invoice = next(row for row in invoices if row["id"] == invoice_id)
    assert invoice["status"] == "part_paid"
    assert invoice["allocated"] == "60.00"
    assert invoice["outstanding"] == "40.00"

    bank_account = client.post(
        "/api/v1/banking/accounts",
        headers=headers,
        json={
            "name": "Settlement Bank",
            "currency": "GBP",
            "ledger_account_id": accounts["1000"],
        },
    ).get_json()["id"]
    bank_transaction = client.post(
        "/api/v1/banking/transactions",
        headers=headers,
        json={
            "bank_account_id": bank_account,
            "date": "2026-09-14",
            "description": "Final customer receipt",
            "amount": "40.00",
        },
    ).get_json()["id"]
    reconciliation = client.post(
        f"/api/v1/banking/transactions/{bank_transaction}/post-and-match",
        headers=headers,
        json={
            "offset_account_id": accounts["1200"],
            "reference": "BANK-40",
            "description": "Final customer receipt",
        },
    )
    assert reconciliation.status_code == 201
    bank_journal_id = reconciliation.get_json()["journal_id"]

    adopted = client.post(
        "/api/v1/sales/payments/adopt-journal",
        headers=headers,
        json={
            "customer_id": customer,
            "journal_id": bank_journal_id,
            "receivable_account_id": accounts["1200"],
        },
    )
    assert adopted.status_code == 201
    assert adopted.get_json()["amount"] == "40.00"
    adopted_payment_id = adopted.get_json()["id"]

    final_allocation = client.post(
        f"/api/v1/sales/payments/{adopted_payment_id}/allocate",
        headers=headers,
        json={"allocations": [{"invoice_id": invoice_id, "amount": "40.00"}]},
    )
    assert final_allocation.status_code == 200

    invoices = client.get("/api/v1/sales/invoices", headers=headers).get_json()["invoices"]
    invoice = next(row for row in invoices if row["id"] == invoice_id)
    assert invoice["status"] == "paid"
    assert invoice["outstanding"] == "0.00"

    with app.app_context():
        assert Journal.query.count() == 3  # invoice, first payment, reconciled bank journal
        stored = db.session.get(SalesInvoice, invoice_id)
        assert stored.status == "paid"

    trial = client.get("/api/v1/ledger/trial-balance", headers=headers).get_json()["rows"]
    by_code = {row["code"]: row for row in trial}
    assert by_code["1200"]["balance"] == "0.00"
    assert by_code["1000"]["balance"] == "100.00"


def test_supplier_payment_can_be_allocated_to_bill(client, app):
    token, accounts = _setup(app)
    headers = _headers(token)

    supplier = client.post(
        "/api/v1/purchases/suppliers",
        headers=headers,
        json={"name": "Settlement Supplier"},
    ).get_json()["id"]
    bill_response = client.post(
        "/api/v1/purchases/bills",
        headers=headers,
        json={
            "supplier_id": supplier,
            "bill_number": "BILL-PAY-001",
            "bill_date": "2026-09-14",
            "amount": "75.00",
            "payable_account_id": accounts["2100"],
            "expense_account_id": accounts["5000"],
            "description": "Office costs",
        },
    )
    assert bill_response.status_code == 201
    bill_id = bill_response.get_json()["id"]

    payment = client.post(
        "/api/v1/purchases/payments",
        headers=headers,
        json={
            "supplier_id": supplier,
            "date": "2026-09-14",
            "amount": "75.00",
            "bank_account_id": accounts["1000"],
            "payable_account_id": accounts["2100"],
            "reference": "SUP-75",
        },
    )
    assert payment.status_code == 201
    payment_id = payment.get_json()["id"]

    allocation = client.post(
        f"/api/v1/purchases/payments/{payment_id}/allocate",
        headers=headers,
        json={"allocations": [{"bill_id": bill_id, "amount": "75.00"}]},
    )
    assert allocation.status_code == 200
    assert allocation.get_json()["status"] == "allocated"

    bills = client.get("/api/v1/purchases/bills", headers=headers).get_json()["bills"]
    bill = next(row for row in bills if row["id"] == bill_id)
    assert bill["status"] == "paid"
    assert bill["outstanding"] == "0.00"

    with app.app_context():
        assert db.session.get(PurchaseBill, bill_id).status == "paid"

    trial = client.get("/api/v1/ledger/trial-balance", headers=headers).get_json()["rows"]
    by_code = {row["code"]: row for row in trial}
    assert by_code["2100"]["balance"] == "0.00"
    assert by_code["1000"]["balance"] == "-75.00"


def test_payment_posting_respects_locked_period(client, app):
    token, accounts = _setup(app)
    headers = _headers(token)
    customer = client.post(
        "/api/v1/sales/customers", headers=headers, json={"name": "Locked Customer"}
    ).get_json()["id"]
    period = client.post(
        "/api/v1/ledger/periods",
        headers=headers,
        json={"name": "August 2026", "start_date": "2026-08-01", "end_date": "2026-08-31"},
    ).get_json()["id"]
    locked = client.post(
        f"/api/v1/ledger/periods/{period}/lock",
        headers=headers,
        json={"locked": True},
    )
    assert locked.status_code == 200

    payment = client.post(
        "/api/v1/sales/payments",
        headers=headers,
        json={
            "customer_id": customer,
            "date": "2026-08-20",
            "amount": "10.00",
            "bank_account_id": accounts["1000"],
            "receivable_account_id": accounts["1200"],
        },
    )
    assert payment.status_code == 400
    assert "locked period" in payment.get_json()["error"]
