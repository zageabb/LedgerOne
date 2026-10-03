from __future__ import annotations

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session


class FinalisedBankReconciliationImmutableError(RuntimeError):
    pass


_installed = False


def _guard(session: Session, flush_context, instances):
    from ledgerone.modules.banking.models import BankReconciliation

    for obj in list(session.dirty):
        if isinstance(obj, BankReconciliation) and sa_inspect(obj).persistent:
            state = sa_inspect(obj)
            history = state.attrs.status.history
            previous = set(history.deleted)
            was_finalised = "finalised" in previous or (not previous and obj.status == "finalised")
            if was_finalised:
                changed = {
                    attr.key
                    for attr in state.mapper.column_attrs
                    if state.attrs[attr.key].history.has_changes()
                }
                if changed:
                    raise FinalisedBankReconciliationImmutableError(
                        "Finalised bank reconciliation evidence is immutable"
                    )

    for obj in list(session.deleted):
        if isinstance(obj, BankReconciliation) and obj.status == "finalised":
            raise FinalisedBankReconciliationImmutableError(
                "Finalised bank reconciliation evidence cannot be deleted"
            )


def install_bank_reconciliation_immutability_guard():
    global _installed
    if _installed:
        return
    event.listen(Session, "before_flush", _guard)
    _installed = True
