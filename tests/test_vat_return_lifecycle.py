from datetime import date
from decimal import Decimal

import pytest

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account
from ledgerone.module_registry import module_registry
from ledgerone.modules.sales.credits import SalesCreditService
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.tax.models import TaxCode, VATAdjustment
from ledgerone.modules.tax.services import TaxError, TaxService
from ledgerone.services.context import AccessContext
from ledgerone.services.document_immutability import PostedDocumentImmutableError


def _setup():
    organisation = Organisation.query.one()
    context = AccessContext.system(organisation.id)
    if not module_registry.is_enabled(organisation.id, "tax"):
        SettingsService.set_module_enabled(context, "tax", True)
    TaxService.update_profile(
        context,
        jurisdiction="GB",
        is_vat_registered=True,
        registration_number="GB123456789",
        scheme="standard",
        return_frequency="quarterly",
    )
    accounts = {
        row.code: row.id
        for row in Account.query.filter_by(organisation_id=organisation.id).all()
    }
    tax_code = TaxCode.query.filter_by(
        organisation_id=organisation.id, code="T20"
    ).one()
    customer = SalesService.create_customer(context, name="VAT Lifecycle Customer")
    return context, accounts, tax_code, customer


def _invoice(
    context,
    accounts,
    tax_code,
    customer,
    *,
    number,
    invoice_date,
    tax_point,
    amount="100.00",
):
    return SalesService.create_invoice(
        context,
        customer_id=customer.id,
        invoice_number=number,
        invoice_date=invoice_date,
        tax_point=tax_point,
        due_date=None,
        description="Taxable service",
        amount=amount,
        receivable_account_id=accounts["1200"],
        revenue_account_id=accounts["4000"],
        tax_code_id=tax_code.id,
    )


def test_vat_return_uses_tax_point_not_invoice_date(app):
    with app.app_context():
        context, accounts, tax_code, customer = _setup()
        invoice = _invoice(
            context,
            accounts,
            tax_code,
            customer,
            number="TP-INV-001",
            invoice_date=date(2026, 9, 30),
            tax_point=date(2026, 10, 1),
        )

        september = TaxService.vat_return(
            context, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30)
        )
        october = TaxService.vat_return(
            context, start_date=date(2026, 10, 1), end_date=date(2026, 10, 31)
        )

        assert invoice.tax_point == date(2026, 10, 1)
        assert september["box_1_output_vat"] == Decimal("0.00")
        assert september["box_6_sales_net"] == Decimal("0.00")
        assert october["box_1_output_vat"] == Decimal("20.00")
        assert october["box_6_sales_net"] == Decimal("100.00")


def test_credit_note_uses_its_own_tax_point(app):
    with app.app_context():
        context, accounts, tax_code, customer = _setup()
        invoice = _invoice(
            context,
            accounts,
            tax_code,
            customer,
            number="TP-INV-002",
            invoice_date=date(2026, 10, 1),
            tax_point=date(2026, 10, 1),
        )
        credit = SalesCreditService.create_credit_note(
            context,
            invoice_id=invoice.id,
            credit_number="TP-CN-001",
            credit_date=date(2026, 11, 2),
            tax_point=date(2026, 10, 20),
            amount="50.00",
            description="October price adjustment",
        )

        october = TaxService.vat_return(
            context, start_date=date(2026, 10, 1), end_date=date(2026, 10, 31)
        )
        november = TaxService.vat_return(
            context, start_date=date(2026, 11, 1), end_date=date(2026, 11, 30)
        )

        assert credit.tax_point == date(2026, 10, 20)
        assert october["box_1_output_vat"] == Decimal("10.00")
        assert october["box_6_sales_net"] == Decimal("50.00")
        assert october["sales_credit_notes"] == 1
        assert november["box_1_output_vat"] == Decimal("0.00")
        assert november["sales_credit_notes"] == 0


def test_adjustment_is_audited_and_frozen_into_final_return(app):
    with app.app_context():
        context, accounts, tax_code, customer = _setup()
        invoice = _invoice(
            context,
            accounts,
            tax_code,
            customer,
            number="TP-INV-003",
            invoice_date=date(2026, 10, 5),
            tax_point=date(2026, 10, 5),
        )
        adjustment = TaxService.create_adjustment(
            context,
            tax_point=date(2026, 10, 10),
            box_number="1",
            amount="5.00",
            reason="Manual correction supported by VAT working paper",
            evidence_reference="WP-VAT-2026-Q4-01",
        )
        period = TaxService.create_return_period(
            context,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )

        period = TaxService.finalise_return_period(context, period.id)
        summary = TaxService.return_period_summary(context, period.id)
        db.session.refresh(adjustment)

        assert period.status == "final"
        assert summary["box_1_output_vat"] == Decimal("25.00")
        assert summary["adjustments_count"] == 1
        assert invoice.id in period.snapshot_json["population"]["sales_invoice_ids"]
        assert adjustment.id in period.snapshot_json["population"]["adjustment_ids"]
        assert adjustment.return_period_id == period.id

        actions = {
            row.action
            for row in AuditEvent.query.filter_by(organisation_id=context.organisation_id).all()
        }
        assert "vat_adjustment_created" in actions
        assert "vat_return_finalised" in actions


def test_finalised_return_blocks_late_entry_and_remains_reproducible(app):
    with app.app_context():
        context, accounts, tax_code, customer = _setup()
        _invoice(
            context,
            accounts,
            tax_code,
            customer,
            number="TP-INV-004",
            invoice_date=date(2026, 10, 2),
            tax_point=date(2026, 10, 2),
        )
        period = TaxService.create_return_period(
            context,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
        )
        TaxService.finalise_return_period(context, period.id)
        frozen = TaxService.return_period_summary(context, period.id)

        with pytest.raises(TaxError, match="inside final return period"):
            _invoice(
                context,
                accounts,
                tax_code,
                customer,
                number="TP-LATE-001",
                invoice_date=date(2026, 11, 5),
                tax_point=date(2026, 10, 15),
            )

        with pytest.raises(TaxError, match="inside final return period"):
            TaxService.create_adjustment(
                context,
                tax_point=date(2026, 10, 15),
                box_number="1",
                amount="1.00",
                reason="Should be rejected after finalisation",
            )

        submitted = TaxService.mark_return_submitted(
            context,
            period.id,
            submission_reference="HMRC-TEST-RECEIPT-001",
            submission_note="Externally filed test return",
        )
        reproduced = TaxService.return_period_summary(context, period.id)

        assert submitted.status == "submitted"
        assert submitted.submission_reference == "HMRC-TEST-RECEIPT-001"
        assert reproduced == frozen


def test_posted_invoice_tax_point_is_immutable(app):
    with app.app_context():
        context, accounts, tax_code, customer = _setup()
        invoice = _invoice(
            context,
            accounts,
            tax_code,
            customer,
            number="TP-INV-005",
            invoice_date=date(2026, 10, 5),
            tax_point=date(2026, 10, 4),
        )

        invoice.tax_point = date(2026, 10, 6)
        with pytest.raises(PostedDocumentImmutableError, match="tax_point"):
            db.session.commit()
        db.session.rollback()


def test_vat_return_lifecycle_routes_are_registered(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/tax/vat-returns" in rules
    assert "/api/v1/tax/return-periods" in rules
    assert "/api/v1/tax/return-periods/<period_id>/finalise" in rules
    assert "/api/v1/tax/return-periods/<period_id>/submit" in rules
    assert "/api/v1/tax/adjustments" in rules
