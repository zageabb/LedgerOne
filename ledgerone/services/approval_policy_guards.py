from __future__ import annotations

import inspect
from functools import wraps

from ledgerone.services.approval_policy import ApprovalPolicyService


_installed = False


def _bound_payload(original, context, args, kwargs):
    bound = inspect.signature(original).bind_partial(context, *args, **kwargs)
    payload = {
        key: value
        for key, value in bound.arguments.items()
        if key not in {"context", "commit", "enforce_permission"}
    }
    return payload


def _result_reference(result):
    if result is None:
        return {}
    for key in ("id", "journal_id"):
        value = getattr(result, key, None)
        if value:
            return {"id": str(value)}
    return {"result": str(result)[:200]}


def _wrap(cls, name, policy_key, *, amount_key=None, title=None, condition=None):
    original = getattr(cls, name)
    if getattr(original, "_approval_policy_guarded", False):
        return

    @wraps(original)
    def guarded(context, *args, **kwargs):
        payload = _bound_payload(original, context, args, kwargs)
        if condition and not condition(context, payload):
            return original(context, *args, **kwargs)
        amount = payload.get(amount_key) if amount_key else None
        workflow = ApprovalPolicyService.guard(
            context,
            policy_key,
            payload=payload,
            title=(title or name.replace("_", " ").title()),
            amount=amount,
        )
        result = original(context, *args, **kwargs)
        ApprovalPolicyService.consume(context, workflow, result=_result_reference(result))
        return result

    guarded._approval_policy_guarded = True
    setattr(cls, name, staticmethod(guarded))


def install_approval_policy_guards():
    global _installed
    if _installed:
        return

    from ledgerone.modules.banking.services import BankingService
    from ledgerone.modules.purchases.services import PurchasesService
    from ledgerone.modules.sales.services import SalesService
    from ledgerone.services.control_accounts import ControlAccountService
    from ledgerone.services.period_policy import PERIOD_OPEN, PeriodPolicyService

    _wrap(
        SalesService,
        "create_customer",
        "master_data",
        title="Approve customer master-data change",
    )
    _wrap(
        PurchasesService,
        "create_supplier",
        "master_data",
        title="Approve supplier master-data change",
    )
    _wrap(
        SalesService,
        "record_payment",
        "payment",
        amount_key="amount",
        title="Approve customer payment",
    )
    _wrap(
        PurchasesService,
        "record_payment",
        "payment",
        amount_key="amount",
        title="Approve supplier payment",
    )
    _wrap(
        BankingService,
        "post_and_match",
        "bank_posting",
        title="Approve bank posting",
    )

    def reopening(context, payload):
        status = str(payload.get("status") or "").strip().lower()
        if status != PERIOD_OPEN:
            return False
        period_id = payload.get("period_id")
        from ledgerone.extensions import db
        from ledgerone.models.ledger import AccountingPeriod
        period = db.session.get(AccountingPeriod, period_id)
        return bool(
            period
            and period.organisation_id == context.organisation_id
            and str(period.status or "").strip().lower() not in {"open"}
        )

    _wrap(
        PeriodPolicyService,
        "set_period_status",
        "period_reopen",
        title="Approve accounting-period reopen",
        condition=reopening,
    )
    _wrap(
        ControlAccountService,
        "post_adjustment",
        "control_adjustment",
        title="Approve control-account adjustment",
    )

    _installed = True
