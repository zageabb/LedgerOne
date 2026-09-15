from datetime import date

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Organisation
from ledgerone.models.ledger import Account, AccountingPeriod, Journal
from ledgerone.services.context import AccessContext


def _domain_types():
    # Import after the Flask app has completed module discovery. Importing Purchases at
    # pytest collection time walks PDF/Documents dependencies before their packages are
    # fully initialised and creates a false circular-import failure.
    from ledgerone.modules.purchases.models import PurchaseBill
    from ledgerone.modules.sales.models import SalesInvoice
    from ledgerone.modules.workflows.models import WorkflowInstance

    return PurchaseBill, SalesInvoice, WorkflowInstance


def _api_setup(app):
    with app.app_context():
        from ledgerone.modules.purchases.services import PurchasesService
        from ledgerone.modules.sales.services import SalesService

        organisation = Organisation.query.one()
        key, token = ApiKey.issue(
            name="workflow-boundary",
            organisation_id=organisation.id,
            full_access=True,
        )
        db.session.add(key)
        context = AccessContext.system(organisation.id)
        supplier = PurchasesService.create_supplier(context, name="API Workflow Supplier")
        customer = SalesService.create_customer(context, name="API Workflow Customer")
        accounts = {
            row.code: row.id
            for row in Account.query.filter_by(organisation_id=organisation.id).all()
        }
        db.session.commit()
        return token, accounts, supplier.id, customer.id


def test_manual_journal_api_creates_workflow_not_journal_by_default(client, app):
    token, accounts, _, _ = _api_setup(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "date": "2026-09-15",
            "reference": "API-WF-JRN",
            "description": "API controlled journal",
            "lines": [
                {"account_id": accounts["1000"], "debit": "50.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "50.00"},
            ],
        },
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["posted"] is False
    assert data["status"] == "awaiting_review"
    assert "workflow_instance_id" in data
    with app.app_context():
        _, _, WorkflowInstance = _domain_types()
        assert Journal.query.count() == 0
        workflow = db.session.get(WorkflowInstance, data["workflow_instance_id"])
        assert workflow.entity_type == "journal"
        assert workflow.source_module == "api"


def test_purchase_bill_api_creates_workflow_without_ap_entry(client, app):
    token, accounts, supplier_id, _ = _api_setup(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/purchases/bills",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "bill_number": "API-WF-BILL",
            "bill_date": "2026-09-15",
            "due_date": "2026-10-15",
            "description": "API controlled purchase",
            "amount": "100.00",
            "payable_account_id": accounts["2100"],
            "expense_account_id": accounts["5000"],
            "currency": "GBP",
        },
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["posted"] is False
    assert data["status"] == "awaiting_review"
    with app.app_context():
        PurchaseBill, _, WorkflowInstance = _domain_types()
        assert PurchaseBill.query.filter_by(bill_number="API-WF-BILL").count() == 0
        assert Journal.query.count() == 0
        workflow = db.session.get(WorkflowInstance, data["workflow_instance_id"])
        assert workflow.entity_type == "purchase_bill"
        assert workflow.source_module == "api"


def test_sales_invoice_api_creates_workflow_without_ar_entry(client, app):
    token, accounts, _, customer_id = _api_setup(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "API-WF-INV",
            "invoice_date": "2026-09-15",
            "due_date": "2026-10-15",
            "description": "API controlled sale",
            "amount": "100.00",
            "receivable_account_id": accounts["1200"],
            "revenue_account_id": accounts["4000"],
            "currency": "GBP",
        },
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["posted"] is False
    assert data["status"] == "awaiting_review"
    with app.app_context():
        _, SalesInvoice, WorkflowInstance = _domain_types()
        assert SalesInvoice.query.filter_by(invoice_number="API-WF-INV").count() == 0
        assert Journal.query.count() == 0
        workflow = db.session.get(WorkflowInstance, data["workflow_instance_id"])
        assert workflow.entity_type == "sales_invoice"
        assert workflow.source_module == "api"


def test_api_journal_still_rejects_invalid_accounting_before_workflow_creation(client, app):
    token, accounts, _, _ = _api_setup(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/ledger/journals",
        headers=headers,
        json={
            "description": "Unbalanced proposal must fail",
            "lines": [
                {"account_id": accounts["1000"], "debit": "50.00", "credit": "0"},
                {"account_id": accounts["4000"], "debit": "0", "credit": "40.00"},
            ],
        },
    )

    assert response.status_code == 400
    assert "not balanced" in response.get_json()["error"]
    with app.app_context():
        _, _, WorkflowInstance = _domain_types()
        assert Journal.query.count() == 0
        assert WorkflowInstance.query.filter_by(entity_type="journal").count() == 0


def test_locked_period_sales_invoice_is_rejected_before_workflow_creation(client, app):
    token, accounts, _, customer_id = _api_setup(app)
    headers = {"Authorization": f"Bearer {token}"}

    with app.app_context():
        organisation = Organisation.query.one()
        db.session.add(
            AccountingPeriod(
                organisation_id=organisation.id,
                name="September 2026",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 30),
                status="locked",
            )
        )
        db.session.commit()

    response = client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_number": "API-WF-LOCKED",
            "invoice_date": "2026-09-15",
            "due_date": "2026-10-15",
            "description": "Locked-period proposal",
            "amount": "100.00",
            "receivable_account_id": accounts["1200"],
            "revenue_account_id": accounts["4000"],
            "currency": "GBP",
        },
    )

    assert response.status_code == 400
    assert "locked period September 2026" in response.get_json()["error"]
    with app.app_context():
        _, SalesInvoice, WorkflowInstance = _domain_types()
        assert SalesInvoice.query.filter_by(invoice_number="API-WF-LOCKED").count() == 0
        assert Journal.query.count() == 0
        assert WorkflowInstance.query.filter_by(entity_type="sales_invoice").count() == 0
