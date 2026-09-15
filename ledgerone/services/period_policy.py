from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from flask import current_app

from ledgerone.extensions import db
from ledgerone.models.core import Setting, utcnow
from ledgerone.models.ledger import AccountingPeriod
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError


class PeriodPolicyError(LedgerError):
    """Raised when accounting-period governance prevents a posting or transition."""


POLICY_OPTIONAL = "optional"
POLICY_REQUIRED = "required"
POLICIES = {POLICY_OPTIONAL, POLICY_REQUIRED}
PERIOD_OPEN = "open"
PERIOD_SOFT_CLOSED = "soft_closed"
PERIOD_HARD_CLOSED = "hard_closed"
PERIOD_STATUSES = {PERIOD_OPEN, PERIOD_SOFT_CLOSED, PERIOD_HARD_CLOSED}
LEGACY_HARD_CLOSED = "locked"

_override_reason: ContextVar[str | None] = ContextVar(
    "ledgerone_period_override_reason", default=None
)
_guards_installed = False


def _normalise_policy(value: str | None) -> str:
    value = (value or "").strip().lower()
    return value if value in POLICIES else POLICY_REQUIRED


def _normalise_status(value: str | None) -> str:
    value = (value or "").strip().lower()
    if value == LEGACY_HARD_CLOSED:
        return PERIOD_HARD_CLOSED
    return value


@contextmanager
def _override_scope(reason: str | None):
    clean = (reason or "").strip() or None
    token = _override_reason.set(clean)
    try:
        yield
    finally:
        _override_reason.reset(token)


class PeriodPolicyService:
    @staticmethod
    def get_policy(context: AccessContext) -> str:
        if not context.organisation_id:
            raise PeriodPolicyError("An organisation is required")
        row = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope="ledger",
            key="posting_period_policy",
        ).first()
        if row:
            value = row.value
            if isinstance(value, dict):
                value = value.get("mode")
            return _normalise_policy(value)
        return _normalise_policy(current_app.config.get("ACCOUNTING_PERIOD_POLICY", POLICY_REQUIRED))

    @staticmethod
    def set_policy(context: AccessContext, *, mode: str):
        if not context.can("ledger.periods.manage"):
            raise PermissionError("ledger.periods.manage")
        mode = (mode or "").strip().lower()
        if mode not in POLICIES:
            raise PeriodPolicyError("Posting-period policy must be optional or required")
        row = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope="ledger",
            key="posting_period_policy",
        ).first()
        if row is None:
            row = Setting(
                organisation_id=context.organisation_id,
                scope="ledger",
                key="posting_period_policy",
                value={"mode": mode},
            )
            db.session.add(row)
        else:
            row.value = {"mode": mode}
        record_audit_event(
            context,
            module_id="ledger",
            action="posting_period_policy_updated",
            entity_type="setting",
            entity_id=row.id,
            detail={"mode": mode},
        )
        db.session.commit()
        return mode

    @staticmethod
    def containing_period(context: AccessContext, posting_date):
        return AccountingPeriod.query.filter(
            AccountingPeriod.organisation_id == context.organisation_id,
            AccountingPeriod.start_date <= posting_date,
            AccountingPeriod.end_date >= posting_date,
        ).first()

    @staticmethod
    def assert_posting_allowed(context: AccessContext, posting_date):
        period = PeriodPolicyService.containing_period(context, posting_date)
        policy = PeriodPolicyService.get_policy(context)
        if period is None:
            if policy == POLICY_REQUIRED:
                raise PeriodPolicyError(
                    f"Posting date {posting_date.isoformat()} is not inside a defined accounting period"
                )
            return None

        status = _normalise_status(period.status)
        if status == PERIOD_HARD_CLOSED:
            raise PeriodPolicyError(
                f"Posting date {posting_date.isoformat()} is in locked period {period.name} (hard closed)"
            )
        if status == PERIOD_SOFT_CLOSED:
            reason = _override_reason.get()
            if not context.can("ledger.periods.override"):
                raise PeriodPolicyError(
                    f"Posting date {posting_date.isoformat()} is in soft-closed period {period.name}; "
                    "ledger.periods.override permission is required"
                )
            if not reason:
                raise PeriodPolicyError(
                    f"Posting date {posting_date.isoformat()} is in soft-closed period {period.name}; "
                    "an override reason is required"
                )
            record_audit_event(
                context,
                module_id="ledger",
                action="soft_closed_period_override",
                entity_type="accounting_period",
                entity_id=period.id,
                detail={
                    "period": period.name,
                    "posting_date": posting_date.isoformat(),
                    "reason": reason,
                },
            )
        elif status != PERIOD_OPEN:
            raise PeriodPolicyError(f"Accounting period {period.name} has unsupported status {period.status}")
        return period

    @staticmethod
    def set_period_status(
        context: AccessContext,
        period_id: str,
        *,
        status: str,
        reason: str | None = None,
    ):
        if not context.can("ledger.periods.manage"):
            raise PermissionError("ledger.periods.manage")
        period = db.session.get(AccountingPeriod, period_id)
        if not period or period.organisation_id != context.organisation_id:
            raise PeriodPolicyError("Accounting period not found")
        status = _normalise_status(status)
        if status not in PERIOD_STATUSES:
            raise PeriodPolicyError("Period status must be open, soft_closed or hard_closed")

        previous = _normalise_status(period.status)
        clean_reason = (reason or "").strip() or None
        if previous != PERIOD_OPEN and status == PERIOD_OPEN and not clean_reason:
            raise PeriodPolicyError("Reopening a closed accounting period requires a reason")
        if previous == status:
            return period

        period.status = status
        if status == PERIOD_OPEN:
            period.locked_at = None
            period.locked_by_user_id = None
            action = "period_reopened"
        else:
            period.locked_at = utcnow()
            period.locked_by_user_id = context.user_id
            action = "period_soft_closed" if status == PERIOD_SOFT_CLOSED else "period_hard_closed"

        record_audit_event(
            context,
            module_id="ledger",
            action=action,
            entity_type="accounting_period",
            entity_id=period.id,
            detail={
                "name": period.name,
                "previous_status": previous,
                "status": status,
                "reason": clean_reason,
            },
        )
        db.session.commit()
        return period


def install_period_policy_guards() -> None:
    """Apply period governance underneath UI, API, business modules and AI tools."""
    global _guards_installed
    if _guards_installed:
        return

    from ledgerone.services.ledger import LedgerService

    original_post = LedgerService.post_journal
    if not getattr(original_post, "_period_policy_guarded", False):
        @wraps(original_post)
        def guarded_post(context, *args, **kwargs):
            reason = kwargs.pop("period_override_reason", None)
            with _override_scope(reason):
                return original_post(context, *args, **kwargs)

        guarded_post._period_policy_guarded = True
        LedgerService.post_journal = staticmethod(guarded_post)

    original_assert = LedgerService.assert_posting_date_open
    if not getattr(original_assert, "_period_policy_guarded", False):
        @wraps(original_assert)
        def guarded_assert(context, posting_date):
            return PeriodPolicyService.assert_posting_allowed(context, posting_date)

        guarded_assert._period_policy_guarded = True
        LedgerService.assert_posting_date_open = staticmethod(guarded_assert)

    original_lock = LedgerService.set_period_locked
    if not getattr(original_lock, "_period_policy_guarded", False):
        @wraps(original_lock)
        def guarded_lock(context, period_id, *, locked: bool, reason: str | None = None):
            row = PeriodPolicyService.set_period_status(
                context,
                period_id,
                status=PERIOD_HARD_CLOSED if locked else PERIOD_OPEN,
                reason=reason,
            )
            # Keep the v0.2 lock API/browser contract stable while treating legacy
            # `locked` exactly like `hard_closed` in the central posting policy.
            if locked and row.status == PERIOD_HARD_CLOSED:
                row.status = LEGACY_HARD_CLOSED
                db.session.commit()
            return row

        guarded_lock._period_policy_guarded = True
        LedgerService.set_period_locked = staticmethod(guarded_lock)

    _guards_installed = True
