from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import inspect

from ledgerone.extensions import db
from ledgerone.models.ledger import Account
from ledgerone.module_registry import module_registry
from ledgerone.modules.tax.models import TaxCode, TaxProfile
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class TaxError(ValueError):
    pass


def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise TaxError(f"Invalid monetary value: {value}") from exc


class TaxService:
    TREATMENTS = {"standard", "reduced", "zero", "exempt", "out_of_scope"}
    SCOPES = {"sales", "purchase", "both"}

    @staticmethod
    def seed_defaults(organisation_id: str):
        """Seed UK-friendly tax accounts/codes when the tax schema is available."""
        inspector = inspect(db.engine)
        if not inspector.has_table("tax_codes") or not inspector.has_table("tax_profiles"):
            return

        def ensure_account(code: str, name: str, account_type: str):
            row = Account.query.filter_by(organisation_id=organisation_id, code=code).first()
            if row is None:
                row = Account(
                    organisation_id=organisation_id,
                    code=code,
                    name=name,
                    account_type=account_type,
                    is_control_account=True,
                )
                db.session.add(row)
                db.session.flush()
            return row

        input_vat = ensure_account("1300", "VAT Recoverable", "asset")
        output_vat = ensure_account("2200", "VAT Payable", "liability")

        if TaxProfile.query.filter_by(organisation_id=organisation_id).first() is None:
            db.session.add(TaxProfile(organisation_id=organisation_id, jurisdiction="GB"))

        defaults = [
            ("T20", "UK Standard VAT 20%", "20.0000", "standard", True),
            ("T5", "UK Reduced VAT 5%", "5.0000", "reduced", True),
            ("T0", "UK Zero-rated VAT", "0.0000", "zero", True),
            ("EXEMPT", "VAT Exempt", "0.0000", "exempt", True),
            ("OUT", "Outside scope of VAT", "0.0000", "out_of_scope", False),
        ]
        for code, name, rate, treatment, uses_accounts in defaults:
            if TaxCode.query.filter_by(organisation_id=organisation_id, code=code).first():
                continue
            db.session.add(
                TaxCode(
                    organisation_id=organisation_id,
                    code=code,
                    name=name,
                    rate_percent=Decimal(rate),
                    treatment=treatment,
                    scope="both",
                    sales_tax_account_id=output_vat.id if uses_accounts else None,
                    purchase_tax_account_id=input_vat.id if uses_accounts else None,
                )
            )
        db.session.commit()

    @staticmethod
    def profile(context: AccessContext):
        if not context.can("tax.read"):
            raise PermissionError("tax.read")
        row = TaxProfile.query.filter_by(organisation_id=context.organisation_id).first()
        if row is None:
            row = TaxProfile(organisation_id=context.organisation_id)
            db.session.add(row)
            db.session.commit()
        return row

    @staticmethod
    def update_profile(
        context: AccessContext,
        *,
        jurisdiction: str = "GB",
        is_vat_registered: bool = False,
        registration_number: str | None = None,
        scheme: str = "standard",
        return_frequency: str = "quarterly",
    ):
        if not context.can("tax.manage"):
            raise PermissionError("tax.manage")
        scheme = (scheme or "standard").strip().lower()
        if scheme not in {"standard", "cash", "flat_rate"}:
            raise TaxError("VAT scheme must be standard, cash or flat_rate")
        return_frequency = (return_frequency or "quarterly").strip().lower()
        if return_frequency not in {"monthly", "quarterly", "annual"}:
            raise TaxError("Return frequency must be monthly, quarterly or annual")
        row = TaxProfile.query.filter_by(organisation_id=context.organisation_id).first()
        if row is None:
            row = TaxProfile(organisation_id=context.organisation_id)
            db.session.add(row)
        row.jurisdiction = (jurisdiction or "GB").strip().upper()[:10]
        row.is_vat_registered = bool(is_vat_registered)
        row.registration_number = (registration_number or "").strip() or None
        row.scheme = scheme
        row.return_frequency = return_frequency
        db.session.flush()
        record_audit_event(
            context,
            module_id="tax",
            action="tax_profile_updated",
            entity_type="tax_profile",
            entity_id=row.id,
            detail={
                "jurisdiction": row.jurisdiction,
                "is_vat_registered": row.is_vat_registered,
                "scheme": row.scheme,
                "return_frequency": row.return_frequency,
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def list_codes(context: AccessContext, *, active_only: bool = True, usage: str | None = None):
        if not context.can("tax.read"):
            raise PermissionError("tax.read")
        query = TaxCode.query.filter_by(organisation_id=context.organisation_id)
        if active_only:
            query = query.filter(TaxCode.is_active.is_(True))
        if usage in {"sales", "purchase"}:
            query = query.filter(TaxCode.scope.in_([usage, "both"]))
        return query.order_by(TaxCode.code.asc()).all()

    @staticmethod
    def create_code(
        context: AccessContext,
        *,
        code: str,
        name: str,
        rate_percent,
        treatment: str = "standard",
        scope: str = "both",
        sales_tax_account_id: str | None = None,
        purchase_tax_account_id: str | None = None,
    ):
        if not context.can("tax.manage"):
            raise PermissionError("tax.manage")
        code = (code or "").strip().upper()
        name = (name or "").strip()
        if not code or not name:
            raise TaxError("Tax code and name are required")
        if TaxCode.query.filter_by(organisation_id=context.organisation_id, code=code).first():
            raise TaxError(f"Tax code {code} already exists")
        treatment = (treatment or "standard").strip().lower()
        if treatment not in TaxService.TREATMENTS:
            raise TaxError("Invalid tax treatment")
        scope = (scope or "both").strip().lower()
        if scope not in TaxService.SCOPES:
            raise TaxError("Tax scope must be sales, purchase or both")
        try:
            rate = Decimal(str(rate_percent or 0)).quantize(Decimal("0.0001"))
        except InvalidOperation as exc:
            raise TaxError("Invalid tax rate") from exc
        if rate < 0 or rate > 100:
            raise TaxError("Tax rate must be between 0 and 100 percent")
        if treatment in {"zero", "exempt", "out_of_scope"}:
            rate = Decimal("0.0000")

        def account(account_id, expected_type, label):
            if not account_id:
                return None
            row = db.session.get(Account, account_id)
            if not row or row.organisation_id != context.organisation_id:
                raise TaxError(f"Invalid {label} account")
            if row.account_type != expected_type:
                raise TaxError(f"{label} account must be an {expected_type} account")
            return row

        sales_account = account(sales_tax_account_id, "liability", "sales VAT")
        purchase_account = account(purchase_tax_account_id, "asset", "purchase VAT")
        taxable = rate > 0
        if taxable and scope in {"sales", "both"} and sales_account is None:
            raise TaxError("A liability account is required for taxable sales VAT")
        if taxable and scope in {"purchase", "both"} and purchase_account is None:
            raise TaxError("An asset account is required for taxable purchase VAT")

        row = TaxCode(
            organisation_id=context.organisation_id,
            code=code,
            name=name,
            rate_percent=rate,
            treatment=treatment,
            scope=scope,
            sales_tax_account_id=sales_account.id if sales_account else None,
            purchase_tax_account_id=purchase_account.id if purchase_account else None,
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="tax",
            action="tax_code_created",
            entity_type="tax_code",
            entity_id=row.id,
            detail={"code": row.code, "rate_percent": str(row.rate_percent), "scope": row.scope},
        )
        db.session.commit()
        return row

    @staticmethod
    def code_for_use(context: AccessContext, tax_code_id: str | None, usage: str):
        if not tax_code_id:
            return None
        if not module_registry.is_enabled(context.organisation_id, "tax"):
            raise TaxError("Tax/VAT module is disabled for this organisation")
        row = db.session.get(TaxCode, tax_code_id)
        if not row or row.organisation_id != context.organisation_id or not row.is_active:
            raise TaxError("Invalid or inactive tax code")
        if usage not in {"sales", "purchase"}:
            raise TaxError("Invalid tax usage")
        if row.scope not in {usage, "both"}:
            raise TaxError(f"Tax code {row.code} cannot be used for {usage}")
        return row

    @staticmethod
    def tax_amount(net_amount, tax_code: TaxCode | None) -> Decimal:
        net = _money(net_amount)
        if not tax_code or tax_code.treatment in {"zero", "exempt", "out_of_scope"}:
            return Decimal("0.00")
        return (net * Decimal(str(tax_code.rate_percent)) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def vat_return(context: AccessContext, *, start_date: date, end_date: date):
        if not context.can("tax.read"):
            raise PermissionError("tax.read")
        if end_date < start_date:
            raise TaxError("VAT return end date cannot be before start date")
        profile = TaxProfile.query.filter_by(organisation_id=context.organisation_id).first()
        if profile and profile.jurisdiction != "GB":
            raise TaxError("The first VAT return implementation supports GB jurisdiction only")
        if profile and profile.scheme != "standard":
            raise TaxError("The first VAT return implementation supports standard VAT accounting only")

        from ledgerone.modules.purchases.credit_models import PurchaseCreditNote
        from ledgerone.modules.purchases.models import PurchaseBill, PurchaseBillLine
        from ledgerone.modules.sales.credit_models import SalesCreditNote
        from ledgerone.modules.sales.models import SalesInvoice, SalesInvoiceLine

        sales_rows = (
            db.session.query(SalesInvoice, SalesInvoiceLine, TaxCode)
            .join(SalesInvoiceLine, SalesInvoiceLine.invoice_id == SalesInvoice.id)
            .join(TaxCode, TaxCode.id == SalesInvoiceLine.tax_code_id)
            .filter(
                SalesInvoice.organisation_id == context.organisation_id,
                SalesInvoice.invoice_date >= start_date,
                SalesInvoice.invoice_date <= end_date,
                SalesInvoice.posted_journal_id.is_not(None),
            )
            .all()
        )
        purchase_rows = (
            db.session.query(PurchaseBill, PurchaseBillLine, TaxCode)
            .join(PurchaseBillLine, PurchaseBillLine.bill_id == PurchaseBill.id)
            .join(TaxCode, TaxCode.id == PurchaseBillLine.tax_code_id)
            .filter(
                PurchaseBill.organisation_id == context.organisation_id,
                PurchaseBill.bill_date >= start_date,
                PurchaseBill.bill_date <= end_date,
                PurchaseBill.posted_journal_id.is_not(None),
            )
            .all()
        )
        sales_credit_rows = (
            db.session.query(SalesCreditNote, TaxCode)
            .join(SalesInvoice, SalesInvoice.id == SalesCreditNote.invoice_id)
            .join(SalesInvoiceLine, SalesInvoiceLine.invoice_id == SalesInvoice.id)
            .join(TaxCode, TaxCode.id == SalesInvoiceLine.tax_code_id)
            .filter(
                SalesCreditNote.organisation_id == context.organisation_id,
                SalesCreditNote.credit_date >= start_date,
                SalesCreditNote.credit_date <= end_date,
                SalesCreditNote.status == "posted",
            )
            .all()
        )
        purchase_credit_rows = (
            db.session.query(PurchaseCreditNote, TaxCode)
            .join(PurchaseBill, PurchaseBill.id == PurchaseCreditNote.bill_id)
            .join(PurchaseBillLine, PurchaseBillLine.bill_id == PurchaseBill.id)
            .join(TaxCode, TaxCode.id == PurchaseBillLine.tax_code_id)
            .filter(
                PurchaseCreditNote.organisation_id == context.organisation_id,
                PurchaseCreditNote.credit_date >= start_date,
                PurchaseCreditNote.credit_date <= end_date,
                PurchaseCreditNote.status == "posted",
            )
            .all()
        )

        sales_vat = sum(
            (_money(line.tax_amount) for _, line, code in sales_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )
        sales_credit_vat = sum(
            (_money(note.tax_total) for note, code in sales_credit_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )
        purchase_vat = sum(
            (_money(line.tax_amount) for _, line, code in purchase_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )
        purchase_credit_vat = sum(
            (_money(note.tax_total) for note, code in purchase_credit_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )
        sales_net = sum(
            (_money(line.net_amount) for _, line, code in sales_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )
        sales_credit_net = sum(
            (_money(note.subtotal) for note, code in sales_credit_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )
        purchase_net = sum(
            (_money(line.net_amount) for _, line, code in purchase_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )
        purchase_credit_net = sum(
            (_money(note.subtotal) for note, code in purchase_credit_rows if code.treatment != "out_of_scope"),
            Decimal("0.00"),
        )

        box_1 = sales_vat - sales_credit_vat
        box_4 = purchase_vat - purchase_credit_vat
        box_6 = sales_net - sales_credit_net
        box_7 = purchase_net - purchase_credit_net
        net = box_1 - box_4
        return {
            "from_date": start_date,
            "to_date": end_date,
            "vat_registered": bool(profile and profile.is_vat_registered),
            "registration_number": profile.registration_number if profile else None,
            "box_1_output_vat": box_1,
            "box_2_acquisitions_vat": Decimal("0.00"),
            "box_3_total_vat_due": box_1,
            "box_4_input_vat": box_4,
            "box_5_net_vat": abs(net),
            "net_vat_due": net,
            "position": "payable" if net > 0 else ("repayment" if net < 0 else "nil"),
            "box_6_sales_net": box_6,
            "box_7_purchases_net": box_7,
            "box_8_eu_supplies": Decimal("0.00"),
            "box_9_eu_acquisitions": Decimal("0.00"),
            "sales_documents": len({invoice.id for invoice, _, code in sales_rows if code.treatment != "out_of_scope"}),
            "purchase_documents": len({bill.id for bill, _, code in purchase_rows if code.treatment != "out_of_scope"}),
            "sales_credit_notes": len([1 for note, code in sales_credit_rows if code.treatment != "out_of_scope"]),
            "purchase_credit_notes": len([1 for note, code in purchase_credit_rows if code.treatment != "out_of_scope"]),
        }
