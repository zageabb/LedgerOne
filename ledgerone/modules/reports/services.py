from datetime import date
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.purchases.models import (
    PurchaseBill,
    PurchasePayment,
    PurchasePaymentAllocation,
)
from ledgerone.modules.sales.models import (
    SalesInvoice,
    SalesPayment,
    SalesPaymentAllocation,
)
from ledgerone.services.context import AccessContext
from ledgerone.services.reporting import FinancialReportingService


class ReportsService:
    AGING_BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")

    @staticmethod
    def summary(
        context: AccessContext,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        compare_from: date | None = None,
        compare_to: date | None = None,
        compare_as_of: date | None = None,
    ):
        return FinancialReportingService.summary(
            context,
            from_date=from_date,
            to_date=to_date,
            compare_from=compare_from,
            compare_to=compare_to,
            compare_as_of=compare_as_of,
        )

    @staticmethod
    def profit_and_loss(
        context: AccessContext,
        *,
        from_date: date,
        to_date: date,
        compare_from: date | None = None,
        compare_to: date | None = None,
    ):
        return FinancialReportingService.profit_and_loss(
            context,
            from_date=from_date,
            to_date=to_date,
            compare_from=compare_from,
            compare_to=compare_to,
        )

    @staticmethod
    def balance_sheet(
        context: AccessContext,
        *,
        as_of: date,
        compare_as_of: date | None = None,
    ):
        return FinancialReportingService.balance_sheet(
            context,
            as_of=as_of,
            compare_as_of=compare_as_of,
        )

    @staticmethod
    def trial_balance(
        context: AccessContext,
        *,
        as_of: date | None = None,
        from_date: date | None = None,
    ):
        return FinancialReportingService.trial_balance(
            context,
            as_of=as_of,
            from_date=from_date,
        )

    @staticmethod
    def general_ledger(
        context: AccessContext,
        *,
        from_date: date,
        to_date: date,
        account_id: str | None = None,
    ):
        return FinancialReportingService.general_ledger(
            context,
            from_date=from_date,
            to_date=to_date,
            account_id=account_id,
        )

    @staticmethod
    def _bucket(days_overdue: int) -> str:
        if days_overdue <= 0:
            return "current"
        if days_overdue <= 30:
            return "1_30"
        if days_overdue <= 60:
            return "31_60"
        if days_overdue <= 90:
            return "61_90"
        return "90_plus"

    @staticmethod
    def _empty_currency_totals():
        return {
            "current": Decimal("0.00"),
            "1_30": Decimal("0.00"),
            "31_60": Decimal("0.00"),
            "61_90": Decimal("0.00"),
            "90_plus": Decimal("0.00"),
            "total": Decimal("0.00"),
        }

    @staticmethod
    def _sales_allocated_as_of(invoice_id: str, as_of: date) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(SalesPaymentAllocation.amount), 0))
            .join(SalesPayment, SalesPayment.id == SalesPaymentAllocation.payment_id)
            .filter(
                SalesPaymentAllocation.invoice_id == invoice_id,
                SalesPayment.payment_date <= as_of,
            )
            .scalar()
        )
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))

    @staticmethod
    def _purchase_allocated_as_of(bill_id: str, as_of: date) -> Decimal:
        value = (
            db.session.query(db.func.coalesce(db.func.sum(PurchasePaymentAllocation.amount), 0))
            .join(PurchasePayment, PurchasePayment.id == PurchasePaymentAllocation.payment_id)
            .filter(
                PurchasePaymentAllocation.bill_id == bill_id,
                PurchasePayment.payment_date <= as_of,
            )
            .scalar()
        )
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))

    @staticmethod
    def aged_receivables(context: AccessContext, *, as_of: date | None = None):
        as_of = as_of or date.today()
        rows = []
        totals_by_currency = {}
        invoices = (
            SalesInvoice.query.filter(
                SalesInvoice.organisation_id == context.organisation_id,
                SalesInvoice.invoice_date <= as_of,
            )
            .order_by(SalesInvoice.due_date.asc(), SalesInvoice.invoice_date.asc())
            .all()
        )
        for invoice in invoices:
            outstanding = max(
                Decimal("0.00"),
                Decimal(str(invoice.total)).quantize(Decimal("0.01"))
                - ReportsService._sales_allocated_as_of(invoice.id, as_of),
            )
            if outstanding == 0:
                continue
            due_date = invoice.due_date or invoice.invoice_date
            days_overdue = (as_of - due_date).days
            bucket = ReportsService._bucket(days_overdue)
            currency = invoice.currency or "GBP"
            totals = totals_by_currency.setdefault(
                currency, ReportsService._empty_currency_totals()
            )
            totals[bucket] += outstanding
            totals["total"] += outstanding
            rows.append(
                {
                    "id": invoice.id,
                    "number": invoice.invoice_number,
                    "party_id": invoice.customer_id,
                    "party_name": invoice.customer.name,
                    "document_date": invoice.invoice_date,
                    "due_date": due_date,
                    "days_overdue": max(0, days_overdue),
                    "bucket": bucket,
                    "currency": currency,
                    "outstanding": outstanding,
                }
            )
        rows.sort(key=lambda item: (item["days_overdue"], item["due_date"]), reverse=True)
        return {"as_of": as_of, "rows": rows, "totals_by_currency": totals_by_currency}

    @staticmethod
    def aged_payables(context: AccessContext, *, as_of: date | None = None):
        as_of = as_of or date.today()
        rows = []
        totals_by_currency = {}
        bills = (
            PurchaseBill.query.filter(
                PurchaseBill.organisation_id == context.organisation_id,
                PurchaseBill.bill_date <= as_of,
            )
            .order_by(PurchaseBill.due_date.asc(), PurchaseBill.bill_date.asc())
            .all()
        )
        for bill in bills:
            outstanding = max(
                Decimal("0.00"),
                Decimal(str(bill.total)).quantize(Decimal("0.01"))
                - ReportsService._purchase_allocated_as_of(bill.id, as_of),
            )
            if outstanding == 0:
                continue
            due_date = bill.due_date or bill.bill_date
            days_overdue = (as_of - due_date).days
            bucket = ReportsService._bucket(days_overdue)
            currency = bill.currency or "GBP"
            totals = totals_by_currency.setdefault(
                currency, ReportsService._empty_currency_totals()
            )
            totals[bucket] += outstanding
            totals["total"] += outstanding
            rows.append(
                {
                    "id": bill.id,
                    "number": bill.bill_number,
                    "party_id": bill.supplier_id,
                    "party_name": bill.supplier.name,
                    "document_date": bill.bill_date,
                    "due_date": due_date,
                    "days_overdue": max(0, days_overdue),
                    "bucket": bucket,
                    "currency": currency,
                    "outstanding": outstanding,
                }
            )
        rows.sort(key=lambda item: (item["days_overdue"], item["due_date"]), reverse=True)
        return {"as_of": as_of, "rows": rows, "totals_by_currency": totals_by_currency}
