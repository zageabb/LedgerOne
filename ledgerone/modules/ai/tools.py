from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable

from ledgerone.models.ledger import Journal
from ledgerone.module_registry import module_registry
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


@dataclass(frozen=True)
class ToolSpec:
    name: str
    module_id: str
    description: str
    write: bool
    permission: str
    handler: Callable[[AccessContext, dict], object]


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _list_accounts(context, args):
    return [
        {"id": row.id, "code": row.code, "name": row.name, "account_type": row.account_type, "currency": row.currency}
        for row in LedgerService.list_accounts(context)
    ]


def _trial_balance(context, args):
    return [
        {key: _json_value(value) for key, value in row.items()}
        for row in LedgerService.trial_balance(context)
    ]


def _list_journals(context, args):
    if not context.can("ledger.read"):
        raise PermissionError("Missing permission: ledger.read")
    limit = min(int(args.get("limit", 50)), 200)
    rows = (
        Journal.query.filter_by(organisation_id=context.organisation_id)
        .order_by(Journal.journal_date.desc(), Journal.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "date": row.journal_date.isoformat(),
            "reference": row.reference,
            "description": row.description,
            "source_module": row.source_module,
            "debit": str(row.total_debit),
            "credit": str(row.total_credit),
        }
        for row in rows
    ]


def _create_account(context, args):
    row = LedgerService.create_account(
        context,
        code=args["code"],
        name=args["name"],
        account_type=args["account_type"],
        currency=args.get("currency"),
        parent_id=args.get("parent_id"),
    )
    return {"id": row.id, "code": row.code, "name": row.name}


def _post_journal(context, args):
    row = LedgerService.post_journal(
        context,
        journal_date=date.fromisoformat(args.get("date") or date.today().isoformat()),
        description=args.get("description", "AI journal"),
        reference=args.get("reference"),
        lines=args.get("lines") or [],
        source_module="ai",
        source_reference=args.get("source_reference"),
        metadata={"created_by": "ledgerone_ai"},
    )
    return {"id": row.id, "status": row.status}


def _bank_accounts(context, args):
    from ledgerone.modules.banking.services import BankingService
    return [
        {"id": row.id, "name": row.name, "institution": row.institution, "currency": row.currency, "ledger_account_id": row.ledger_account_id}
        for row in BankingService.list_accounts(context)
    ]


def _bank_transactions(context, args):
    from ledgerone.modules.banking.services import BankingService
    return [
        {"id": row.id, "bank_account_id": row.bank_account_id, "date": row.transaction_date.isoformat(), "description": row.description, "amount": str(row.amount), "status": row.status}
        for row in BankingService.list_transactions(context, min(int(args.get("limit", 100)), 500))
    ]


def _customers(context, args):
    from ledgerone.modules.sales.services import SalesService
    return [{"id": row.id, "name": row.name, "email": row.email} for row in SalesService.list_customers(context)]


def _sales_invoices(context, args):
    from ledgerone.modules.sales.services import SalesService
    return [
        {"id": row.id, "invoice_number": row.invoice_number, "customer_id": row.customer_id, "date": row.invoice_date.isoformat(), "status": row.status, "total": str(row.total)}
        for row in SalesService.list_invoices(context, min(int(args.get("limit", 100)), 500))
    ]


def _create_customer(context, args):
    from ledgerone.modules.sales.services import SalesService
    row = SalesService.create_customer(context, name=args["name"], email=args.get("email"), phone=args.get("phone"))
    return {"id": row.id, "name": row.name}


def _create_invoice(context, args):
    from ledgerone.modules.sales.services import SalesService
    row = SalesService.create_invoice(
        context,
        customer_id=args["customer_id"],
        invoice_number=args["invoice_number"],
        invoice_date=date.fromisoformat(args.get("invoice_date") or date.today().isoformat()),
        due_date=date.fromisoformat(args["due_date"]) if args.get("due_date") else None,
        description=args.get("description", "Sales"),
        amount=args["amount"],
        receivable_account_id=args["receivable_account_id"],
        revenue_account_id=args["revenue_account_id"],
        currency=args.get("currency", "GBP"),
    )
    return {"id": row.id, "status": row.status, "journal_id": row.posted_journal_id}


def _suppliers(context, args):
    from ledgerone.modules.purchases.services import PurchasesService
    return [{"id": row.id, "name": row.name, "email": row.email} for row in PurchasesService.list_suppliers(context)]


def _purchase_bills(context, args):
    from ledgerone.modules.purchases.services import PurchasesService
    return [
        {"id": row.id, "bill_number": row.bill_number, "supplier_id": row.supplier_id, "date": row.bill_date.isoformat(), "status": row.status, "total": str(row.total)}
        for row in PurchasesService.list_bills(context, min(int(args.get("limit", 100)), 500))
    ]


def _create_supplier(context, args):
    from ledgerone.modules.purchases.services import PurchasesService
    row = PurchasesService.create_supplier(context, name=args["name"], email=args.get("email"), phone=args.get("phone"))
    return {"id": row.id, "name": row.name}


def _create_bill(context, args):
    from ledgerone.modules.purchases.services import PurchasesService
    row = PurchasesService.create_bill(
        context,
        supplier_id=args["supplier_id"],
        bill_number=args["bill_number"],
        bill_date=date.fromisoformat(args.get("bill_date") or date.today().isoformat()),
        due_date=date.fromisoformat(args["due_date"]) if args.get("due_date") else None,
        description=args.get("description", "Purchase"),
        amount=args["amount"],
        payable_account_id=args["payable_account_id"],
        expense_account_id=args["expense_account_id"],
        currency=args.get("currency", "GBP"),
    )
    return {"id": row.id, "status": row.status, "journal_id": row.posted_journal_id}


def _audit_events(context, args):
    from ledgerone.modules.audit.services import AuditService

    from_date = date.fromisoformat(args["from_date"]) if args.get("from_date") else None
    to_date = date.fromisoformat(args["to_date"]) if args.get("to_date") else None
    rows, total = AuditService.search(
        context,
        module_id=args.get("module_id") or None,
        action=args.get("action") or None,
        actor_type=args.get("actor_type") or None,
        entity_type=args.get("entity_type") or None,
        from_date=from_date,
        to_date=to_date,
        text=args.get("text") or None,
        limit=min(int(args.get("limit", 50)), 200),
        offset=0,
    )
    return {
        "total": total,
        "events": [AuditService.serialise(row) for row in rows],
    }


TOOLS = {
    spec.name: spec
    for spec in [
        ToolSpec("ledger.list_accounts", "ledger", "List chart-of-account records and IDs.", False, "ledger.read", _list_accounts),
        ToolSpec("ledger.trial_balance", "ledger", "Return the current trial balance.", False, "ledger.read", _trial_balance),
        ToolSpec("ledger.list_journals", "ledger", "List recent posted journals.", False, "ledger.read", _list_journals),
        ToolSpec("ledger.create_account", "ledger", "Create a chart-of-accounts account.", True, "ledger.accounts.write", _create_account),
        ToolSpec("ledger.post_journal", "ledger", "Post a balanced journal. Requires account IDs and debit/credit lines.", True, "ledger.journals.post", _post_journal),
        ToolSpec("banking.list_accounts", "banking", "List bank accounts.", False, "banking.read", _bank_accounts),
        ToolSpec("banking.list_transactions", "banking", "List recent bank transactions.", False, "banking.read", _bank_transactions),
        ToolSpec("sales.list_customers", "sales", "List customers and IDs.", False, "sales.read", _customers),
        ToolSpec("sales.list_invoices", "sales", "List sales invoices.", False, "sales.read", _sales_invoices),
        ToolSpec("sales.create_customer", "sales", "Create a customer.", True, "sales.write", _create_customer),
        ToolSpec("sales.create_invoice", "sales", "Create and post a simple sales invoice.", True, "sales.write", _create_invoice),
        ToolSpec("purchases.list_suppliers", "purchases", "List suppliers and IDs.", False, "purchases.read", _suppliers),
        ToolSpec("purchases.list_bills", "purchases", "List purchase bills.", False, "purchases.read", _purchase_bills),
        ToolSpec("purchases.create_supplier", "purchases", "Create a supplier.", True, "purchases.write", _create_supplier),
        ToolSpec("purchases.create_bill", "purchases", "Create and post a simple purchase bill.", True, "purchases.write", _create_bill),
        ToolSpec("audit.list_events", "audit", "Search recent LedgerOne audit events. Supports module_id, action, actor_type, entity_type, from_date, to_date, text and limit.", False, "audit.read", _audit_events),
    ]
}


def available_tools(context: AccessContext, *, allow_writes: bool = True):
    """Return only tools that both organisation policy and caller permissions allow.

    The organisation-level AI write policy can remove write capability, but it can never
    add a permission the requesting user/API key does not already possess.
    """
    if not context or not context.organisation_id:
        return {}
    return {
        name: spec
        for name, spec in TOOLS.items()
        if module_registry.is_enabled(context.organisation_id, spec.module_id)
        and context.can(spec.permission)
        and (allow_writes or not spec.write)
    }
