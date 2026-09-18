from __future__ import annotations

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session


class VATReturnImmutableError(RuntimeError):
    """Raised when frozen VAT return evidence is altered in place."""


_guard_installed = False


def _changed_fields(target) -> set[str]:
    state = sa_inspect(target)
    return {
        attr.key
        for attr in state.mapper.column_attrs
        if state.attrs[attr.key].history.has_changes()
    }


def _previous_status(target) -> str | None:
    state = sa_inspect(target)
    history = state.attrs.status.history
    deleted = [value for value in history.deleted if value is not None]
    if deleted:
        return deleted[0]
    if state.persistent:
        return getattr(target, "status", None)
    return None


def _locked_period(session: Session, period_id: str | None):
    if not period_id:
        return None
    from ledgerone.modules.tax.models import VATReturnPeriod

    period = session.get(VATReturnPeriod, period_id)
    if period and period.status in {"final", "submitted"}:
        return period
    return None


def _adjustment_original_period_id(target) -> str | None:
    state = sa_inspect(target)
    history = state.attrs.return_period_id.history
    deleted = [value for value in history.deleted if value]
    if deleted:
        return deleted[0]
    return getattr(target, "return_period_id", None)


def _guard_vat_return_evidence(session: Session, flush_context, instances) -> None:
    from ledgerone.modules.tax.models import VATAdjustment, VATReturnPeriod

    for obj in list(session.dirty):
        if isinstance(obj, VATReturnPeriod):
            old_status = _previous_status(obj)
            changed = _changed_fields(obj)
            if old_status == "submitted" and changed:
                raise VATReturnImmutableError(
                    "Submitted VAT return evidence is immutable"
                )
            if old_status == "final":
                allowed = {
                    "status",
                    "submitted_by_user_id",
                    "submitted_at",
                    "submission_reference",
                    "submission_note",
                    "updated_at",
                }
                if obj.status != "submitted" or changed - allowed:
                    raise VATReturnImmutableError(
                        "Final VAT return snapshot is immutable; only the controlled "
                        "final-to-submitted transition is permitted"
                    )
            elif old_status == "draft" and obj.status == "final":
                allowed = {
                    "status",
                    "snapshot_json",
                    "finalised_by_user_id",
                    "finalised_at",
                    "updated_at",
                }
                if changed - allowed:
                    raise VATReturnImmutableError(
                        "VAT return finalisation attempted to alter fields outside the "
                        "frozen return snapshot lifecycle"
                    )
        elif isinstance(obj, VATAdjustment):
            period = _locked_period(session, _adjustment_original_period_id(obj))
            if period and _changed_fields(obj):
                raise VATReturnImmutableError(
                    "VAT adjustment included in a final/submitted return is immutable"
                )

    for obj in list(session.new):
        if isinstance(obj, VATAdjustment):
            period = _locked_period(session, obj.return_period_id)
            if period:
                raise VATReturnImmutableError(
                    "Cannot attach a new VAT adjustment directly to a final/submitted return"
                )

    for obj in list(session.deleted):
        if isinstance(obj, VATReturnPeriod) and obj.status in {"final", "submitted"}:
            raise VATReturnImmutableError(
                "Final/submitted VAT return evidence cannot be deleted"
            )
        if isinstance(obj, VATAdjustment):
            period = _locked_period(session, _adjustment_original_period_id(obj))
            if period:
                raise VATReturnImmutableError(
                    "VAT adjustment included in a final/submitted return cannot be deleted"
                )


def install_vat_return_immutability_guard() -> None:
    global _guard_installed
    if _guard_installed:
        return
    event.listen(Session, "before_flush", _guard_vat_return_evidence)
    _guard_installed = True
