"""Trading posting cannot bypass enabled company approval policies."""
from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.purchases.models import PurchaseBill
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.workflows.models import UserAction
from ledgerone.modules.workflows.purchase_bill_requests import PurchaseBillWorkflowService
from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService
from ledgerone.modules.workflows.services import WorkflowService
from ledgerone.services.approval_policy import ApprovalPolicyService
from ledgerone.services.company import CompanyService
from ledgerone.services.context import AccessContext

DATE = date(2026, 9, 15)
DUE = date(2026, 10, 15)


def _maker():
    org = Organisation.query.first()
    user = User.query.first()
    user.ui_mode = "home"
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org.id,
                         user_id=user.id, full_access=True, permissions=frozenset({"*"}))


def _checker(org_id):
    user = User(email="checker-trading@example.test", name="Checker", ui_mode="professional")
    user.set_password("safe-password")
    db.session.add(user)
    db.session.flush()
    db.session.add(Membership(organisation_id=org_id, user_id=user.id,
                              role="manager", permissions=["workflows.read", "workflows.approve"]))
    db.session.commit()
    return AccessContext(identity_type="user", organisation_id=org_id,
                         user_id=user.id, permissions=frozenset({"workflows.read", "workflows.approve"}))


def _accounts(org):
    return {x.code: x for x in Account.query.filter_by(organisation_id=org).all()}


def _invoice_args(org, customer_id):
    accounts = _accounts(org)
    return dict(customer_id=customer_id, invoice_number="GATED-S-001", invoice_date=DATE,
                due_date=DUE, description="Consulting", amount="120.00",
                receivable_account_id=accounts["1200"].id,
                revenue_account_id=accounts["4000"].id, currency="GBP")


def _bill_args(org, supplier_id):
    accounts = _accounts(org)
    return dict(supplier_id=supplier_id, bill_number="GATED-P-001",
                supplier_invoice_reference="EXT-500", bill_date=DATE, due_date=DUE,
                description="Stationery", amount="120.00",
                payable_account_id=accounts["2100"].id,
                expense_account_id=accounts["5000"].id, currency="GBP")


def _approve(checker, workflow_id):
    action = UserAction.query.filter_by(workflow_instance_id=workflow_id,
                                        action_type="approve", status="open").one()
    WorkflowService.complete_action(checker, action.id, decision="approve")
    return UserAction.query.filter_by(workflow_instance_id=workflow_id,
                                      action_type="post", status="open").one()


def test_sales_invoice_direct_post_needs_independent_approval(app):
    with app.app_context():
        maker = _maker()
        checker = _checker(maker.organisation_id)
        customer = SalesService.create_customer(maker, name="Gate customer")
        args = _invoice_args(maker.organisation_id, customer.id)
        ApprovalPolicyService.set(maker, "sales_invoice", enabled=True,
                                  threshold="100.00", approval_role="manager")
        before = (SalesInvoice.query.count(), Journal.query.count())
        with pytest.raises(ValueError, match="Independent approval required"):
            SalesService.create_invoice(maker, **args)
        assert (SalesInvoice.query.count(), Journal.query.count()) == before

        workflow = SalesInvoiceWorkflowService.create_request(maker, **args)
        post = _approve(checker, workflow.id)
        with pytest.raises(ValueError, match="differs"):
            SalesService.create_invoice(maker, **{**args, "description": "Changed"},
                                        approved_workflow_id=workflow.id)
        invoice = SalesInvoiceWorkflowService.post_from_action(maker, post.id)
        assert invoice.status == "posted"
        assert SalesInvoice.query.count() == before[0] + 1


def test_purchase_bill_direct_post_needs_independent_approval(app):
    with app.app_context():
        maker = _maker()
        checker = _checker(maker.organisation_id)
        supplier = PurchasesService.create_supplier(maker, name="Gate supplier")
        args = _bill_args(maker.organisation_id, supplier.id)
        ApprovalPolicyService.set(maker, "purchase_bill", enabled=True,
                                  threshold="100.00", approval_role="manager")
        before = (PurchaseBill.query.count(), Journal.query.count())
        with pytest.raises(ValueError, match="Independent approval required"):
            PurchasesService.create_bill(maker, **args)
        assert (PurchaseBill.query.count(), Journal.query.count()) == before

        workflow = PurchaseBillWorkflowService.create_request(maker, **args)
        post = _approve(checker, workflow.id)
        with pytest.raises(ValueError, match="differs"):
            PurchasesService.create_bill(maker, **{**args, "supplier_invoice_reference": "TAMPERED"},
                                         approved_workflow_id=workflow.id)
        bill = PurchaseBillWorkflowService.post_from_action(maker, post.id)
        assert bill.status == "posted"
        assert bill.supplier_invoice_reference == "EXT-500"
        assert PurchaseBill.query.count() == before[0] + 1


def test_company_global_threshold_also_gates_trading_and_cannot_reuse_other_company_workflow(app):
    with app.app_context():
        maker = _maker()
        checker = _checker(maker.organisation_id)
        customer = SalesService.create_customer(maker, name="Threshold customer")
        args = _invoice_args(maker.organisation_id, customer.id)
        WorkflowService.set_approval_policy(maker, enabled=True, threshold="100.00",
                                            approval_role="manager")
        with pytest.raises(ValueError, match="Independent approval required"):
            SalesService.create_invoice(maker, **args)
        workflow = SalesInvoiceWorkflowService.create_request(maker, **args)
        _approve(checker, workflow.id)
        other = CompanyService.create(maker, name="Other", company_code="OTHER")
        alternate = AccessContext(identity_type="user", organisation_id=other.id,
                                  user_id=maker.user_id, full_access=True)
        WorkflowService.set_approval_policy(alternate, enabled=True, threshold="100.00")
        second_customer = SalesService.create_customer(alternate, name="Other customer")
        other_args = _invoice_args(other.id, second_customer.id)
        with pytest.raises(ValueError, match="Independent approval required"):
            SalesService.create_invoice(alternate, **other_args,
                                        approved_workflow_id=workflow.id)
