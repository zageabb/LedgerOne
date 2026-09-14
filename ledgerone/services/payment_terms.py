from __future__ import annotations

from datetime import date, timedelta

from ledgerone.extensions import db
from ledgerone.models.core import Setting
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class PaymentTermsService:
    SCOPE = "payment_terms"
    KEY = "defaults"
    DEFAULT_CUSTOMER_DAYS = 30
    DEFAULT_SUPPLIER_DAYS = 30

    @staticmethod
    def _days(value, *, label: str) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} payment terms must be a whole number of days") from exc
        if days < 0 or days > 365:
            raise ValueError(f"{label} payment terms must be between 0 and 365 days")
        return days

    @staticmethod
    def get(organisation_id: str) -> dict:
        row = Setting.query.filter_by(
            organisation_id=organisation_id,
            scope=PaymentTermsService.SCOPE,
            key=PaymentTermsService.KEY,
        ).first()
        value = row.value if row and isinstance(row.value, dict) else {}
        return {
            "customer_days": PaymentTermsService._days(
                value.get("customer_days", PaymentTermsService.DEFAULT_CUSTOMER_DAYS),
                label="Customer",
            ),
            "supplier_days": PaymentTermsService._days(
                value.get("supplier_days", PaymentTermsService.DEFAULT_SUPPLIER_DAYS),
                label="Supplier",
            ),
        }

    @staticmethod
    def update(context: AccessContext, *, customer_days, supplier_days) -> dict:
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        customer_days = PaymentTermsService._days(customer_days, label="Customer")
        supplier_days = PaymentTermsService._days(supplier_days, label="Supplier")
        row = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=PaymentTermsService.SCOPE,
            key=PaymentTermsService.KEY,
        ).first()
        before = PaymentTermsService.get(context.organisation_id)
        if row is None:
            row = Setting(
                organisation_id=context.organisation_id,
                scope=PaymentTermsService.SCOPE,
                key=PaymentTermsService.KEY,
            )
            db.session.add(row)
        row.value = {"customer_days": customer_days, "supplier_days": supplier_days}
        record_audit_event(
            context,
            module_id="settings",
            action="payment_terms_updated",
            entity_type="setting",
            entity_id=row.id,
            detail={"before": before, "after": row.value},
        )
        db.session.commit()
        return dict(row.value)

    @staticmethod
    def customer_days(organisation_id: str, override: int | None = None) -> int:
        if override is not None:
            return PaymentTermsService._days(override, label="Customer")
        return PaymentTermsService.get(organisation_id)["customer_days"]

    @staticmethod
    def supplier_days(organisation_id: str, override: int | None = None) -> int:
        if override is not None:
            return PaymentTermsService._days(override, label="Supplier")
        return PaymentTermsService.get(organisation_id)["supplier_days"]

    @staticmethod
    def customer_due_date(organisation_id: str, document_date: date, override: int | None = None) -> date:
        return document_date + timedelta(days=PaymentTermsService.customer_days(organisation_id, override))

    @staticmethod
    def supplier_due_date(organisation_id: str, document_date: date, override: int | None = None) -> date:
        return document_date + timedelta(days=PaymentTermsService.supplier_days(organisation_id, override))
