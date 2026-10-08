"""Efficient current outstanding balances for customer and supplier registers."""
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.modules.sales.models import SalesInvoice, SalesPayment, SalesPaymentAllocation
from ledgerone.modules.purchases.models import PurchaseBill, PurchasePayment, PurchasePaymentAllocation


def _party_outstanding(organisation_id, document_model, payment_model, allocation_model, party_field, document_field):
    # A grouped document query plus one grouped allocation query, independent of register size.
    docs = (
        db.session.query(
            getattr(document_model, party_field).label("party_id"),
            db.func.coalesce(db.func.sum(document_model.total), 0).label("total"),
        )
        .filter(document_model.organisation_id == organisation_id)
        .group_by(getattr(document_model, party_field))
        .all()
    )
    paid = (
        db.session.query(
            getattr(document_model, party_field).label("party_id"),
            db.func.coalesce(db.func.sum(allocation_model.amount), 0).label("allocated"),
        )
        .join(document_model, getattr(document_model, "id") == getattr(allocation_model, document_field))
        .join(payment_model, payment_model.id == allocation_model.payment_id)
        .filter(document_model.organisation_id == organisation_id, payment_model.organisation_id == organisation_id)
        .group_by(getattr(document_model, party_field))
        .all()
    )
    totals = {row.party_id: Decimal(str(row.total or 0)) for row in docs}
    for row in paid:
        totals[row.party_id] = totals.get(row.party_id, Decimal("0")) - Decimal(str(row.allocated or 0))
    return totals


def customer_balances(context):
    return _party_outstanding(
        context.organisation_id, SalesInvoice, SalesPayment, SalesPaymentAllocation,
        "customer_id", "invoice_id",
    )


def supplier_balances(context):
    return _party_outstanding(
        context.organisation_id, PurchaseBill, PurchasePayment, PurchasePaymentAllocation,
        "supplier_id", "bill_id",
    )
