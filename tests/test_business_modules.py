from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.sales.models import SalesInvoice


def _scoped_key(app, permissions):
    with app.app_context():
        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="pytest-scoped",
            organisation_id=organisation.id,
            permissions=list(permissions),
        )
        db.session.add(key)
        db.session.commit()
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        return token, accounts


def test_sales_permission_can_post_sales_invoice_without_manual_journal_permission(client, app):
    token, accounts = _scoped_key(app, {"sales.read", "sales.write"})
    headers = {"Authorization": f"Bearer {token}"}

    customer_response = client.post(
        "/api/v1/sales/customers",
        headers=headers,
        json={"name": "Test Customer", "email": "customer@example.test"},
    )
    assert customer_response.status_code == 201
    customer_id = customer_response.get_json()["id"]

    invoice_response = client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "INV-TEST-001",
            "invoice_date": "2026-09-14",
            "description": "Consulting",
            "amount": "250.00",
            "receivable_account_id": accounts["1200"],
            "revenue_account_id": accounts["4000"],
            "currency": "GBP",
        },
    )
    assert invoice_response.status_code == 201
    result = invoice_response.get_json()
    assert result["status"] == "posted"
    assert result["journal_id"]

    with app.app_context():
        invoice = SalesInvoice.query.one()
        journal = db.session.get(Journal, invoice.posted_journal_id)
        assert journal.source_module == "sales"
        assert journal.total_debit == Decimal("250.00")
        assert journal.total_credit == Decimal("250.00")

    manual = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "description": "Not allowed",
            "lines": [
                {"account_id": accounts["1000"], "debit": "1.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "1.00"},
            ],
        },
    )
    assert manual.status_code == 403


def test_purchase_permission_can_post_bill_atomically(client, app):
    token, accounts = _scoped_key(app, {"purchases.read", "purchases.write"})
    headers = {"Authorization": f"Bearer {token}"}

    supplier_response = client.post(
        "/api/v1/purchases/suppliers",
        headers=headers,
        json={"name": "Test Supplier"},
    )
    assert supplier_response.status_code == 201
    supplier_id = supplier_response.get_json()["id"]

    bill_response = client.post(
        "/api/v1/purchases/bills",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "bill_number": "BILL-TEST-001",
            "bill_date": "2026-09-14",
            "description": "Office costs",
            "amount": "75.00",
            "payable_account_id": accounts["2100"],
            "expense_account_id": accounts["5000"],
            "currency": "GBP",
        },
    )
    assert bill_response.status_code == 201
    result = bill_response.get_json()
    assert result["status"] == "posted"
    assert result["journal_id"]

    with app.app_context():
        bill = PurchaseBill.query.one()
        journal = db.session.get(Journal, bill.posted_journal_id)
        assert journal.source_module == "purchases"
        assert journal.total_debit == Decimal("75.00")
        assert journal.total_credit == Decimal("75.00")
