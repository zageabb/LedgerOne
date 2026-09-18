from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import inspect

from ledgerone.extensions import db
from ledgerone.models.core import utcnow
from ledgerone.models.ledger import Account
from ledgerone.module_registry import module_registry
from ledgerone.modules.tax.models import TaxCode, TaxProfile, VATAdjustment, VATReturnPeriod
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
    def _validate_return_profile(context: AccessContext):
        profile = TaxProfile.query.filter_by(organisation_id=context.organisation_id).first()
        if profile and profile.jurisdiction != "GB":
            raise TaxError("The VAT return lifecycle currently supports GB jurisdiction only")
        if profile and profile.scheme != "standard":
            raise TaxError("The VAT return lifecycle currently supports standard VAT accounting only")
        return profile

    @staticmethod
    def assert_tax_point_open(context: AccessContext, tax_point: date) -> None:
        locked = VATReturnPeriod.query.filter(
            VATReturnPeriod.organisation_id == context.organisation_id,
            VATReturnPeriod.start_date <= tax_point,
            VATReturnPeriod.end_date >= tax_point,
            VATReturnPeriod.status.in_(["final", "submitted"]),
        ).first()
        if locked:
            raise TaxError(
                f"VAT tax point {tax_point.isoformat()} is inside "
                f"{locked.status} return period {locked.start_date.isoformat()} to "
                f"{locked.end_date.isoformat()}. Record a VAT adjustment in an open period "
                "instead of changing a locked return population."
            )

    @staticmethod
    def list_adjustments(
        context: AccessContext,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        if not context.can("tax.read"):
            raise PermissionError("tax.read")
        query = VATAdjustment.query.filter_by(organisation_id=context.organisation_id)
        if start_date is not None:
            query = query.filter(VATAdjustment.tax_point >= start_date)
        if end_date is not None:
            query = query.filter(VATAdjustment.tax_point <= end_date)
        return query.order_by(VATAdjustment.tax_point.desc(), VATAdjustment.created_at.desc()).all()

    @staticmethod
    def create_adjustment(
        context: AccessContext,
        *,
        tax_point: date,
        box_number: str,
        amount,
        reason: str,
        evidence_reference: str | None = None,
    ):
        if not context.can("tax.manage"):
            raise PermissionError("tax.manage")
        TaxService._validate_return_profile(context)
        box_number = str(box_number or "").strip()
        if box_number not in {"1", "4", "6", "7"}:
            raise TaxError("VAT adjustments currently support boxes 1, 4, 6 and 7")
        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise TaxError("VAT adjustment reason is required")
        value = _money(amount)
        if value == Decimal("0.00"):
            raise TaxError("VAT adjustment amount cannot be zero")
        TaxService.assert_tax_point_open(context, tax_point)
        row = VATAdjustment(
            organisation_id=context.organisation_id,
            tax_point=tax_point,
            box_number=box_number,
            amount=value,
            reason=clean_reason,
            evidence_reference=(evidence_reference or "").strip() or None,
            created_by_user_id=context.user_id,
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="tax",
            action="vat_adjustment_created",
            entity_type="vat_adjustment",
            entity_id=row.id,
            detail={
                "tax_point": tax_point.isoformat(),
                "box_number": box_number,
                "amount": str(value),
                "reason": clean_reason,
                "evidence_reference": row.evidence_reference,
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def list_return_periods(context: AccessContext, limit: int = 100):
        if not context.can("tax.read"):
            raise PermissionError("tax.read")
        return (
            VATReturnPeriod.query.filter_by(organisation_id=context.organisation_id)
            .order_by(VATReturnPeriod.end_date.desc(), VATReturnPeriod.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_return_period(context: AccessContext, period_id: str):
        if not (context.can("tax.read") or context.can("tax.manage")):
            raise PermissionError("tax.read")
        row = db.session.get(VATReturnPeriod, period_id)
        if not row or row.organisation_id != context.organisation_id:
            raise TaxError("VAT return period not found")
        return row

    @staticmethod
    def create_return_period(
        context: AccessContext,
        *,
        start_date: date,
        end_date: date,
    ):
        if not context.can("tax.manage"):
            raise PermissionError("tax.manage")
        TaxService._validate_return_profile(context)
        if end_date < start_date:
            raise TaxError("VAT return end date cannot be before start date")
        overlap = VATReturnPeriod.query.filter(
            VATReturnPeriod.organisation_id == context.organisation_id,
            VATReturnPeriod.start_date <= end_date,
            VATReturnPeriod.end_date >= start_date,
        ).first()
        if overlap:
            raise TaxError(
                "VAT return period overlaps an existing return period "
                f"{overlap.start_date.isoformat()} to {overlap.end_date.isoformat()}"
            )
        row = VATReturnPeriod(
            organisation_id=context.organisation_id,
            start_date=start_date,
            end_date=end_date,
            status="draft",
            snapshot_json={},
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="tax",
            action="vat_return_period_created",
            entity_type="vat_return_period",
            entity_id=row.id,
            detail={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )
        db.session.commit()
        return row

    @staticmethod
    def _calculate_vat_return(
        context: AccessContext,
        *,
        start_date: date,
        end_date: date,
    ):
        if end_date < start_date:
            raise TaxError("VAT return end date cannot be before start date")
        profile = TaxService._validate_return_profile(context)

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
                SalesInvoice.tax_point >= start_date,
                SalesInvoice.tax_point <= end_date,
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
                PurchaseBill.tax_point >= start_date,
                PurchaseBill.tax_point <= end_date,
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
                SalesCreditNote.tax_point >= start_date,
                SalesCreditNote.tax_point <= end_date,
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
                PurchaseCreditNote.tax_point >= start_date,
                PurchaseCreditNote.tax_point <= end_date,
                PurchaseCreditNote.status == "posted",
            )
            .all()
        )
        adjustments = (
            VATAdjustment.query.filter(
                VATAdjustment.organisation_id == context.organisation_id,
                VATAdjustment.tax_point >= start_date,
                VATAdjustment.tax_point <= end_date,
            )
            .order_by(VATAdjustment.tax_point.asc(), VATAdjustment.created_at.asc())
            .all()
        )

        relevant_sales = [
            (invoice, line, code)
            for invoice, line, code in sales_rows
            if code.treatment != "out_of_scope"
        ]
        relevant_purchases = [
            (bill, line, code)
            for bill, line, code in purchase_rows
            if code.treatment != "out_of_scope"
        ]
        relevant_sales_credits = [
            (note, code) for note, code in sales_credit_rows if code.treatment != "out_of_scope"
        ]
        relevant_purchase_credits = [
            (note, code)
            for note, code in purchase_credit_rows
            if code.treatment != "out_of_scope"
        ]

        box_1 = sum((_money(line.tax_amount) for _, line, _ in relevant_sales), Decimal("0.00"))
        box_1 -= sum((_money(note.tax_total) for note, _ in relevant_sales_credits), Decimal("0.00"))
        box_4 = sum((_money(line.tax_amount) for _, line, _ in relevant_purchases), Decimal("0.00"))
        box_4 -= sum((_money(note.tax_total) for note, _ in relevant_purchase_credits), Decimal("0.00"))
        box_6 = sum((_money(line.net_amount) for _, line, _ in relevant_sales), Decimal("0.00"))
        box_6 -= sum((_money(note.subtotal) for note, _ in relevant_sales_credits), Decimal("0.00"))
        box_7 = sum((_money(line.net_amount) for _, line, _ in relevant_purchases), Decimal("0.00"))
        box_7 -= sum((_money(note.subtotal) for note, _ in relevant_purchase_credits), Decimal("0.00"))

        adjustment_totals = {key: Decimal("0.00") for key in ("1", "4", "6", "7")}
        for adjustment in adjustments:
            adjustment_totals[adjustment.box_number] += _money(adjustment.amount)
        box_1 += adjustment_totals["1"]
        box_4 += adjustment_totals["4"]
        box_6 += adjustment_totals["6"]
        box_7 += adjustment_totals["7"]

        box_2 = Decimal("0.00")
        box_3 = box_1 + box_2
        net = box_3 - box_4
        summary = {
            "from_date": start_date,
            "to_date": end_date,
            "vat_registered": bool(profile and profile.is_vat_registered),
            "registration_number": profile.registration_number if profile else None,
            "box_1_output_vat": _money(box_1),
            "box_2_acquisitions_vat": box_2,
            "box_3_total_vat_due": _money(box_3),
            "box_4_input_vat": _money(box_4),
            "box_5_net_vat": _money(abs(net)),
            "net_vat_due": _money(net),
            "position": "payable" if net > 0 else ("repayment" if net < 0 else "nil"),
            "box_6_sales_net": _money(box_6),
            "box_7_purchases_net": _money(box_7),
            "box_8_eu_supplies": Decimal("0.00"),
            "box_9_eu_acquisitions": Decimal("0.00"),
            "sales_documents": len({invoice.id for invoice, _, _ in relevant_sales}),
            "purchase_documents": len({bill.id for bill, _, _ in relevant_purchases}),
            "sales_credit_notes": len({note.id for note, _ in relevant_sales_credits}),
            "purchase_credit_notes": len({note.id for note, _ in relevant_purchase_credits}),
            "adjustments_count": len(adjustments),
        }
        population = {
            "sales_invoice_ids": sorted({invoice.id for invoice, _, _ in relevant_sales}),
            "sales_invoice_line_ids": sorted({line.id for _, line, _ in relevant_sales}),
            "purchase_bill_ids": sorted({bill.id for bill, _, _ in relevant_purchases}),
            "purchase_bill_line_ids": sorted({line.id for _, line, _ in relevant_purchases}),
            "sales_credit_note_ids": sorted({note.id for note, _ in relevant_sales_credits}),
            "purchase_credit_note_ids": sorted({note.id for note, _ in relevant_purchase_credits}),
            "adjustment_ids": [row.id for row in adjustments],
        }
        return summary, population

    @staticmethod
    def vat_return(context: AccessContext, *, start_date: date, end_date: date):
        if not context.can("tax.read"):
            raise PermissionError("tax.read")
        summary, _ = TaxService._calculate_vat_return(
            context, start_date=start_date, end_date=end_date
        )
        return summary

    @staticmethod
    def _summary_to_snapshot(summary: dict) -> dict:
        stored = {}
        for key, value in summary.items():
            if isinstance(value, Decimal):
                stored[key] = str(value)
            elif isinstance(value, date):
                stored[key] = value.isoformat()
            else:
                stored[key] = value
        return stored

    @staticmethod
    def _summary_from_snapshot(stored: dict) -> dict:
        decimal_keys = {
            "box_1_output_vat", "box_2_acquisitions_vat", "box_3_total_vat_due",
            "box_4_input_vat", "box_5_net_vat", "net_vat_due",
            "box_6_sales_net", "box_7_purchases_net",
            "box_8_eu_supplies", "box_9_eu_acquisitions",
        }
        result = dict(stored or {})
        for key in decimal_keys:
            if key in result:
                result[key] = _money(result[key])
        for key in ("from_date", "to_date"):
            if result.get(key):
                result[key] = date.fromisoformat(result[key])
        return result

    @staticmethod
    def return_period_summary(context: AccessContext, period_id: str):
        row = TaxService.get_return_period(context, period_id)
        if row.status in {"final", "submitted"} and (row.snapshot_json or {}).get("summary"):
            return TaxService._summary_from_snapshot(row.snapshot_json["summary"])
        summary, _ = TaxService._calculate_vat_return(
            context, start_date=row.start_date, end_date=row.end_date
        )
        return summary

    @staticmethod
    def finalise_return_period(context: AccessContext, period_id: str):
        if not context.can("tax.manage"):
            raise PermissionError("tax.manage")
        row = TaxService.get_return_period(context, period_id)
        if row.status != "draft":
            raise TaxError("Only a draft VAT return can be finalised")
        summary, population = TaxService._calculate_vat_return(
            context, start_date=row.start_date, end_date=row.end_date
        )
        row.snapshot_json = {
            "version": 1,
            "summary": TaxService._summary_to_snapshot(summary),
            "population": population,
        }
        row.status = "final"
        row.finalised_by_user_id = context.user_id
        row.finalised_at = utcnow()
        if population["adjustment_ids"]:
            VATAdjustment.query.filter(
                VATAdjustment.organisation_id == context.organisation_id,
                VATAdjustment.id.in_(population["adjustment_ids"]),
            ).update(
                {VATAdjustment.return_period_id: row.id},
                synchronize_session=False,
            )
        record_audit_event(
            context,
            module_id="tax",
            action="vat_return_finalised",
            entity_type="vat_return_period",
            entity_id=row.id,
            detail={
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "source_population": population,
                "summary": row.snapshot_json["summary"],
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def mark_return_submitted(
        context: AccessContext,
        period_id: str,
        *,
        submission_reference: str,
        submission_note: str | None = None,
    ):
        if not context.can("tax.manage"):
            raise PermissionError("tax.manage")
        row = TaxService.get_return_period(context, period_id)
        if row.status != "final":
            raise TaxError("Only a final VAT return can be marked submitted")
        reference = (submission_reference or "").strip()
        if not reference:
            raise TaxError("Submission reference is required")
        row.status = "submitted"
        row.submission_reference = reference
        row.submission_note = (submission_note or "").strip() or None
        row.submitted_by_user_id = context.user_id
        row.submitted_at = utcnow()
        record_audit_event(
            context,
            module_id="tax",
            action="vat_return_marked_submitted",
            entity_type="vat_return_period",
            entity_id=row.id,
            detail={
                "submission_reference": reference,
                "submission_note": row.submission_note,
            },
        )
        db.session.commit()
        return row
