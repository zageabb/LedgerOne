from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import NumberAllocation, Organisation, User
from ledgerone.models.ledger import Account
from ledgerone.modules.sales.models import SalesInvoice
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.sales_invoice_requests import SalesInvoiceWorkflowService
from ledgerone.modules.workflows.services import WorkflowService
from ledgerone.services.context import AccessContext
from ledgerone.services.numbering import NumberingError, NumberSequenceService


def _context(*, professional=False):
    organisation = Organisation.query.first()
    user = User.query.first()
    user.ui_mode = "professional" if professional else "home"
    db.session.commit()
    return AccessContext(
        identity_type="user",
        organisation_id=organisation.id,
        user_id=user.id,
        permissions=frozenset(
            {
                "sales.read",
                "sales.write",
                "workflows.read",
                "workflows.review",
                "workflows.post",
                "settings.manage",
            }
        ),
    )


def _accounts(context):
    return {
        row.code: row
        for row in Account.query.filter_by(organisation_id=context.organisation_id).all()
    }


def _customer(context, name="Numbering Customer"):
    return SalesService.create_customer(context, name=name)


def _direct_invoice(context, customer, accounts, *, number=None, revenue_account_id=None):
    return SalesService.create_invoice(
        context,
        customer_id=customer.id,
        invoice_number=number,
        invoice_date=date(2026, 9, 16),
        due_date=date(2026, 10, 16),
        description="Controlled number sale",
        amount="100.00",
        receivable_account_id=accounts["1200"].id,
        revenue_account_id=revenue_account_id or accounts["4000"].id,
        currency="GBP",
    )


def test_blank_invoice_number_is_allocated_and_linked_atomically(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = _customer(context)

        invoice = _direct_invoice(context, customer, accounts)

        assert invoice.invoice_number == "INV-0001"
        allocation = NumberAllocation.query.filter_by(
            organisation_id=context.organisation_id,
            sequence_key="sales_invoice",
            formatted_number="INV-0001",
        ).one()
        assert allocation.status == "issued"
        assert allocation.entity_type == "sales_invoice"
        assert allocation.entity_id == invoice.id
        assert allocation.manual_override is False
        assert NumberSequenceService.peek(
            context.organisation_id,
            "sales_invoice",
            issue_date=date(2026, 9, 16),
        ) == "INV-0002"


def test_failed_invoice_post_does_not_burn_number(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = _customer(context)

        with pytest.raises(ValueError):
            _direct_invoice(
                context,
                customer,
                accounts,
                revenue_account_id="missing-account",
            )

        assert NumberAllocation.query.filter_by(
            organisation_id=context.organisation_id,
            sequence_key="sales_invoice",
        ).count() == 0
        assert NumberSequenceService.peek(
            context.organisation_id,
            "sales_invoice",
            issue_date=date(2026, 9, 16),
        ) == "INV-0001"

        invoice = _direct_invoice(context, customer, accounts)
        assert invoice.invoice_number == "INV-0001"


def test_workflow_does_not_consume_number_until_final_post(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        customer = _customer(context)

        workflow = SalesInvoiceWorkflowService.create_request(
            context,
            customer_id=customer.id,
            invoice_number=None,
            invoice_date=date(2026, 9, 16),
            due_date=date(2026, 10, 16),
            description="Automatic workflow invoice",
            amount="125.00",
            receivable_account_id=accounts["1200"].id,
            revenue_account_id=accounts["4000"].id,
            currency="GBP",
        )

        assert workflow.status == "awaiting_review"
        assert workflow.metadata_json["sales_invoice_request"]["number_mode"] == "automatic"
        assert workflow.metadata_json["sales_invoice_request"]["invoice_number"] == ""
        assert NumberAllocation.query.filter_by(
            organisation_id=context.organisation_id,
            sequence_key="sales_invoice",
        ).count() == 0
        assert SalesInvoice.query.count() == 0

        review = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="review",
            status="open",
        ).one()
        WorkflowService.complete_action(context, review.id, decision="approve")
        assert NumberAllocation.query.filter_by(
            organisation_id=context.organisation_id,
            sequence_key="sales_invoice",
        ).count() == 0

        post_action = UserAction.query.filter_by(
            workflow_instance_id=workflow.id,
            action_type="post",
            status="open",
        ).one()
        invoice = SalesInvoiceWorkflowService.post_from_action(context, post_action.id)

        assert invoice.invoice_number == "INV-0001"
        workflow = db.session.get(WorkflowInstance, workflow.id)
        assert workflow.metadata_json["issued_invoice_number"] == "INV-0001"
        allocation = NumberAllocation.query.filter_by(
            sequence_key="sales_invoice",
            formatted_number="INV-0001",
        ).one()
        assert allocation.entity_id == invoice.id


def test_manual_legacy_number_is_recorded_without_advancing_controlled_counter(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = _customer(context)

        invoice = _direct_invoice(context, customer, accounts, number="LEGACY-42")

        assert invoice.invoice_number == "LEGACY-42"
        allocation = NumberAllocation.query.filter_by(
            sequence_key="sales_invoice",
            formatted_number="LEGACY-42",
        ).one()
        assert allocation.manual_override is True
        assert allocation.status == "issued"
        assert allocation.entity_id == invoice.id
        assert NumberSequenceService.peek(
            context.organisation_id,
            "sales_invoice",
            issue_date=date(2026, 9, 16),
        ) == "INV-0001"


def test_manual_number_cannot_jump_ahead_in_controlled_series(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = _customer(context)

        with pytest.raises(NumberingError, match="next available number"):
            _direct_invoice(context, customer, accounts, number="INV-0009")

        assert SalesInvoice.query.filter_by(invoice_number="INV-0009").count() == 0
        assert NumberAllocation.query.filter_by(
            sequence_key="sales_invoice",
            formatted_number="INV-0009",
        ).count() == 0
        assert NumberSequenceService.peek(
            context.organisation_id,
            "sales_invoice",
            issue_date=date(2026, 9, 16),
        ) == "INV-0001"


def test_existing_pre_control_invoice_number_is_adopted_before_next_number(app):
    with app.app_context():
        context = _context()
        accounts = _accounts(context)
        customer = _customer(context)

        legacy = SalesInvoice(
            organisation_id=context.organisation_id,
            customer_id=customer.id,
            invoice_number="INV-0001",
            invoice_date=date(2026, 9, 1),
            due_date=date(2026, 10, 1),
            currency="GBP",
            status="posted",
            subtotal=Decimal("20.00"),
            tax_total=Decimal("0.00"),
            total=Decimal("20.00"),
            metadata_json={"legacy": True},
        )
        db.session.add(legacy)
        db.session.commit()
        assert NumberAllocation.query.filter_by(sequence_key="sales_invoice").count() == 0

        invoice = _direct_invoice(context, customer, accounts)

        assert invoice.invoice_number == "INV-0002"
        adopted = NumberAllocation.query.filter_by(
            sequence_key="sales_invoice",
            formatted_number="INV-0001",
        ).one()
        assert adopted.entity_id == legacy.id
        assert adopted.status == "issued"
        current = NumberAllocation.query.filter_by(
            sequence_key="sales_invoice",
            formatted_number="INV-0002",
        ).one()
        assert current.entity_id == invoice.id
