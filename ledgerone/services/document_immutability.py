from __future__ import annotations

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session


class PostedDocumentImmutableError(RuntimeError):
    """Raised when posted financial evidence is edited or deleted in place."""


_guard_installed = False

# Settlement status may legitimately move posted -> part_paid -> paid after allocation.
# Credit settlement may likewise move posted/part_paid -> part_credited -> credited.
# Everything below is accounting/source-document evidence and must instead be corrected
# through credit notes, reversals or other explicit correction workflows.
SALES_INVOICE_PROTECTED_FIELDS = frozenset(
    {
        "organisation_id",
        "customer_id",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "tax_total",
        "total",
        "posted_journal_id",
        "metadata_json",
    }
)
PURCHASE_BILL_PROTECTED_FIELDS = frozenset(
    {
        "organisation_id",
        "supplier_id",
        "bill_number",
        "bill_date",
        "due_date",
        "currency",
        "subtotal",
        "tax_total",
        "total",
        "posted_journal_id",
        "metadata_json",
    }
)
EXPENSE_CLAIM_PROTECTED_FIELDS = frozenset(
    {
        "organisation_id",
        "claimant_user_id",
        "claimant_name",
        "claim_number",
        "claim_date",
        "currency",
        "subtotal",
        "tax_total",
        "total",
        "reimbursement_account_id",
        "approved_at",
        "approved_by_user_id",
        "posted_journal_id",
        "metadata_json",
    }
)


def _changed_fields(target) -> set[str]:
    state = sa_inspect(target)
    return {
        attr.key
        for attr in state.mapper.column_attrs
        if state.attrs[attr.key].history.has_changes()
    }


def _status_was_posted(target, posted_statuses: frozenset[str]) -> bool:
    """Return True only when the row was already posted before this unit of work.

    Services create invoices/bills/claims in an intermediate state and then mark them
    posted in the same transaction. That initial transition must remain possible, while
    any later direct ORM edit of the posted record must be rejected.
    """
    state = sa_inspect(target)
    status_attr = state.attrs.status
    history = status_attr.history
    old_statuses = {value for value in history.deleted if value is not None}
    if old_statuses:
        return bool(old_statuses & posted_statuses)
    return state.persistent and getattr(target, "status", None) in posted_statuses


def _journal_link_was_present(target) -> bool:
    state = sa_inspect(target)
    history = state.attrs.posted_journal_id.history
    old_values = {value for value in history.deleted if value}
    if old_values:
        return True
    # No status transition/history means this is an already-persisted posted record.
    return (
        state.persistent
        and bool(getattr(target, "posted_journal_id", None))
        and not history.added
    )


def _posted_before(target, posted_statuses: frozenset[str]) -> bool:
    return _status_was_posted(target, posted_statuses) or _journal_link_was_present(target)


def _parent_is_immutably_posted(parent, posted_statuses: frozenset[str]) -> bool:
    if parent is None:
        return False
    return _posted_before(parent, posted_statuses)


def _reject_header_mutation(target, protected_fields: frozenset[str], label: str, posted_statuses):
    if not _posted_before(target, posted_statuses):
        return
    changed = _changed_fields(target) & protected_fields
    if changed:
        fields = ", ".join(sorted(changed))
        raise PostedDocumentImmutableError(
            f"Posted {label} accounting fields are immutable ({fields}); "
            "use a credit note, reversal or supported correction workflow instead"
        )


def _reject_document_delete(target, label: str, posted_statuses):
    if _posted_before(target, posted_statuses):
        raise PostedDocumentImmutableError(
            f"Posted {label} is immutable and cannot be deleted; use a supported correction workflow instead"
        )


def _parent_for_line(session: Session, line, relationship_name: str, parent_model, foreign_key_name: str):
    parent = line.__dict__.get(relationship_name)
    if isinstance(parent, parent_model):
        return parent
    parent_id = getattr(line, foreign_key_name, None)
    if not parent_id:
        return None
    for candidate in session.new:
        if isinstance(candidate, parent_model) and candidate.id == parent_id:
            return candidate
    return session.get(parent_model, parent_id)


def _guard_posted_documents(session: Session, flush_context, instances) -> None:
    from ledgerone.modules.expense_claims.models import ExpenseClaim, ExpenseClaimLine
    from ledgerone.modules.purchases.credit_models import PurchaseCreditNote
    from ledgerone.modules.purchases.models import PurchaseBill, PurchaseBillLine
    from ledgerone.modules.sales.credit_models import SalesCreditNote
    from ledgerone.modules.sales.models import SalesInvoice, SalesInvoiceLine

    invoice_posted = frozenset({"posted", "part_paid", "paid", "part_credited", "credited"})
    bill_posted = frozenset({"posted", "part_paid", "paid", "part_credited", "credited"})
    claim_posted = frozenset({"posted"})
    credit_posted = frozenset({"posted"})

    for obj in list(session.dirty):
        if isinstance(obj, SalesInvoice):
            _reject_header_mutation(
                obj, SALES_INVOICE_PROTECTED_FIELDS, "sales invoice", invoice_posted
            )
        elif isinstance(obj, PurchaseBill):
            _reject_header_mutation(
                obj, PURCHASE_BILL_PROTECTED_FIELDS, "purchase bill", bill_posted
            )
        elif isinstance(obj, ExpenseClaim):
            _reject_header_mutation(
                obj, EXPENSE_CLAIM_PROTECTED_FIELDS, "expense claim", claim_posted
            )
        elif isinstance(obj, SalesCreditNote) and _posted_before(obj, credit_posted):
            if _changed_fields(obj):
                raise PostedDocumentImmutableError(
                    "Posted sales credit note is immutable; create a supported corrective transaction instead"
                )
        elif isinstance(obj, PurchaseCreditNote) and _posted_before(obj, credit_posted):
            if _changed_fields(obj):
                raise PostedDocumentImmutableError(
                    "Posted purchase credit note is immutable; create a supported corrective transaction instead"
                )
        elif isinstance(obj, SalesInvoiceLine):
            parent = _parent_for_line(session, obj, "invoice", SalesInvoice, "invoice_id")
            if _parent_is_immutably_posted(parent, invoice_posted):
                raise PostedDocumentImmutableError(
                    "Posted sales invoice lines are immutable; use a credit note or reversal instead"
                )
        elif isinstance(obj, PurchaseBillLine):
            parent = _parent_for_line(session, obj, "bill", PurchaseBill, "bill_id")
            if _parent_is_immutably_posted(parent, bill_posted):
                raise PostedDocumentImmutableError(
                    "Posted purchase bill lines are immutable; use a credit note or reversal instead"
                )
        elif isinstance(obj, ExpenseClaimLine):
            parent = _parent_for_line(session, obj, "claim", ExpenseClaim, "claim_id")
            if _parent_is_immutably_posted(parent, claim_posted):
                raise PostedDocumentImmutableError(
                    "Posted expense claim lines are immutable; use a supported correction workflow instead"
                )

    for obj in list(session.new):
        if isinstance(obj, SalesInvoiceLine):
            parent = _parent_for_line(session, obj, "invoice", SalesInvoice, "invoice_id")
            if _parent_is_immutably_posted(parent, invoice_posted):
                raise PostedDocumentImmutableError("Cannot add a line to a posted sales invoice")
        elif isinstance(obj, PurchaseBillLine):
            parent = _parent_for_line(session, obj, "bill", PurchaseBill, "bill_id")
            if _parent_is_immutably_posted(parent, bill_posted):
                raise PostedDocumentImmutableError("Cannot add a line to a posted purchase bill")
        elif isinstance(obj, ExpenseClaimLine):
            parent = _parent_for_line(session, obj, "claim", ExpenseClaim, "claim_id")
            if _parent_is_immutably_posted(parent, claim_posted):
                raise PostedDocumentImmutableError("Cannot add a line to a posted expense claim")

    for obj in list(session.deleted):
        if isinstance(obj, SalesInvoice):
            _reject_document_delete(obj, "sales invoice", invoice_posted)
        elif isinstance(obj, PurchaseBill):
            _reject_document_delete(obj, "purchase bill", bill_posted)
        elif isinstance(obj, ExpenseClaim):
            _reject_document_delete(obj, "expense claim", claim_posted)
        elif isinstance(obj, SalesCreditNote):
            _reject_document_delete(obj, "sales credit note", credit_posted)
        elif isinstance(obj, PurchaseCreditNote):
            _reject_document_delete(obj, "purchase credit note", credit_posted)
        elif isinstance(obj, SalesInvoiceLine):
            parent = _parent_for_line(session, obj, "invoice", SalesInvoice, "invoice_id")
            if _parent_is_immutably_posted(parent, invoice_posted):
                raise PostedDocumentImmutableError("Cannot delete a line from a posted sales invoice")
        elif isinstance(obj, PurchaseBillLine):
            parent = _parent_for_line(session, obj, "bill", PurchaseBill, "bill_id")
            if _parent_is_immutably_posted(parent, bill_posted):
                raise PostedDocumentImmutableError("Cannot delete a line from a posted purchase bill")
        elif isinstance(obj, ExpenseClaimLine):
            parent = _parent_for_line(session, obj, "claim", ExpenseClaim, "claim_id")
            if _parent_is_immutably_posted(parent, claim_posted):
                raise PostedDocumentImmutableError("Cannot delete a line from a posted expense claim")


def install_document_immutability_guard() -> None:
    global _guard_installed
    if _guard_installed:
        return
    event.listen(Session, "before_flush", _guard_posted_documents)
    _guard_installed = True
