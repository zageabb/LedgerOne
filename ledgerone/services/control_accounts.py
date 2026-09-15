from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from decimal import Decimal
from functools import wraps

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from ledgerone.extensions import db
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class ControlAccountError(ValueError):
    """Raised when a posting bypasses the owner of a control account."""


ROLE_LABELS = {
    "accounts_receivable": "Accounts receivable",
    "accounts_payable": "Accounts payable",
    "output_vat": "Output VAT",
    "input_vat": "Input VAT",
    "employee_reimbursements": "Employee reimbursements",
    "generic": "Control account",
    "conflicted": "Conflicted control account",
}

ROLE_OWNER = {
    "accounts_receivable": "sales",
    "accounts_payable": "purchases",
    "output_vat": "sales",
    "input_vat": "purchases",
    "employee_reimbursements": "expense_claims",
}

ROLE_ALLOWED_MODULES = {
    "accounts_receivable": frozenset({"sales"}),
    "accounts_payable": frozenset({"purchases"}),
    "output_vat": frozenset({"sales"}),
    "input_vat": frozenset({"purchases", "expense_claims"}),
    "employee_reimbursements": frozenset({"expense_claims"}),
}

DEBIT_BALANCE_ROLES = frozenset({"accounts_receivable", "input_vat"})

_active_roles: ContextVar[frozenset[str]] = ContextVar(
    "ledgerone_active_control_account_roles", default=frozenset()
)
_reversal_authorised: ContextVar[bool] = ContextVar(
    "ledgerone_control_account_reversal_authorised", default=False
)
_adjustment_authorised: ContextVar[bool] = ContextVar(
    "ledgerone_control_account_adjustment_authorised", default=False
)

_orm_guard_installed = False
_service_guards_installed = False


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def control_role(account: Account) -> str | None:
    metadata = account.metadata_json or {}
    return metadata.get("control_role") or ("generic" if account.is_control_account else None)


def control_owner(account: Account) -> str | None:
    return (account.metadata_json or {}).get("control_owner_module")


def _assign_control_role(account: Account, role: str, *, strict: bool = False) -> bool:
    if role not in ROLE_OWNER:
        raise ControlAccountError(f"Unsupported control-account role: {role}")

    metadata = dict(account.metadata_json or {})
    existing = metadata.get("control_role")
    if existing and existing not in {role, "generic"}:
        if strict:
            raise ControlAccountError(
                f"Account {account.code} is already assigned to control role {existing}; "
                f"it cannot also be used as {role}."
            )
        conflicts = set(metadata.get("control_conflict_roles") or [])
        if existing != "conflicted":
            conflicts.add(existing)
        conflicts.add(role)
        metadata.update(
            {
                "control_role": "conflicted",
                "control_owner_module": "multiple",
                "control_allowed_modules": [],
                "control_conflict_roles": sorted(conflicts),
            }
        )
    else:
        metadata.update(
            {
                "control_role": role,
                "control_owner_module": ROLE_OWNER[role],
                "control_allowed_modules": sorted(ROLE_ALLOWED_MODULES[role]),
            }
        )
        metadata.pop("control_conflict_roles", None)

    changed = (not account.is_control_account) or metadata != (account.metadata_json or {})
    account.is_control_account = True
    account.metadata_json = metadata
    return changed


def _assign_by_id(
    organisation_id: str | None,
    account_id: str | None,
    role: str,
    *,
    strict: bool = False,
) -> bool:
    if not account_id:
        return False
    account = db.session.get(Account, account_id)
    if not account or account.organisation_id != organisation_id:
        if strict:
            raise ControlAccountError("Invalid control account")
        return False
    return _assign_control_role(account, role, strict=strict)


def seed_control_account_metadata_for_org(organisation_id: str) -> bool:
    """Assign explicit owner/type metadata to known and configured control accounts."""
    inspector = inspect(db.engine)
    if not inspector.has_table("accounts"):
        return False

    changed = False
    defaults = {
        "1200": "accounts_receivable",
        "2100": "accounts_payable",
        "1300": "input_vat",
        "2200": "output_vat",
        "2150": "employee_reimbursements",
    }
    accounts = {
        row.code: row
        for row in Account.query.filter_by(organisation_id=organisation_id).all()
    }
    for code, role in defaults.items():
        account = accounts.get(code)
        if account:
            changed = _assign_control_role(account, role) or changed

    if inspector.has_table("tax_codes"):
        from ledgerone.modules.tax.models import TaxCode

        for tax_code in TaxCode.query.filter_by(organisation_id=organisation_id).all():
            changed = _assign_by_id(
                organisation_id, tax_code.sales_tax_account_id, "output_vat"
            ) or changed
            changed = _assign_by_id(
                organisation_id, tax_code.purchase_tax_account_id, "input_vat"
            ) or changed

    if inspector.has_table("expense_claims"):
        from ledgerone.modules.expense_claims.models import ExpenseClaim

        reimbursement_ids = {
            value
            for (value,) in db.session.query(ExpenseClaim.reimbursement_account_id)
            .filter(ExpenseClaim.organisation_id == organisation_id)
            .distinct()
            .all()
            if value
        }
        for account_id in reimbursement_ids:
            changed = _assign_by_id(
                organisation_id, account_id, "employee_reimbursements"
            ) or changed

    return changed


def seed_all_control_account_metadata() -> None:
    inspector = inspect(db.engine)
    if not inspector.has_table("accounts"):
        return
    organisation_ids = [
        value
        for (value,) in db.session.query(Account.organisation_id).distinct().all()
        if value
    ]
    changed = False
    for organisation_id in organisation_ids:
        changed = seed_control_account_metadata_for_org(organisation_id) or changed
    if changed:
        db.session.commit()


@contextmanager
def _role_scope(*roles: str):
    token = _active_roles.set(frozenset(roles))
    try:
        yield
    finally:
        _active_roles.reset(token)


@contextmanager
def _reversal_scope():
    token = _reversal_authorised.set(True)
    try:
        yield
    finally:
        _reversal_authorised.reset(token)


@contextmanager
def _adjustment_scope():
    token = _adjustment_authorised.set(True)
    try:
        yield
    finally:
        _adjustment_authorised.reset(token)


def _assert_control_post_allowed(account: Account, *, source_module: str | None) -> None:
    role = control_role(account)
    if not role:
        return
    if _reversal_authorised.get() or _adjustment_authorised.get():
        return

    active_roles = _active_roles.get()
    allowed_modules = ROLE_ALLOWED_MODULES.get(role, frozenset())
    if role in active_roles and source_module in allowed_modules:
        return

    owner = control_owner(account) or ROLE_OWNER.get(role) or "its owning subledger"
    label = ROLE_LABELS.get(role, role.replace("_", " ").title())
    if role == "conflicted":
        raise ControlAccountError(
            f"Account {account.code} has conflicting control-account roles and is blocked "
            "until its ownership is corrected."
        )
    raise ControlAccountError(
        f"Account {account.code} ({account.name}) is a {label} control account. "
        f"Post through the {owner} workflow or use an authorised control-account adjustment."
    )


def validate_control_account_lines(
    context: AccessContext,
    lines: list[dict] | None,
    *,
    source_module: str | None,
) -> None:
    for raw in lines or []:
        account_id = raw.get("account_id")
        if not account_id:
            continue
        account = db.session.get(Account, account_id)
        if not account or account.organisation_id != context.organisation_id:
            continue
        _assert_control_post_allowed(account, source_module=source_module)


def _journal_for_line(session: Session, line: JournalLine) -> Journal | None:
    journal = line.__dict__.get("journal")
    if isinstance(journal, Journal):
        return journal
    if line.journal_id:
        for candidate in session.new:
            if isinstance(candidate, Journal) and candidate.id == line.journal_id:
                return candidate
        return session.get(Journal, line.journal_id)
    return None


def _account_for_line(session: Session, line: JournalLine) -> Account | None:
    account = line.__dict__.get("account")
    if isinstance(account, Account):
        return account
    if line.account_id:
        for candidate in session.new:
            if isinstance(candidate, Account) and candidate.id == line.account_id:
                return candidate
        return session.get(Account, line.account_id)
    return None


def _enforce_orm_control_accounts(session: Session, flush_context, instances) -> None:
    """Defence-in-depth for direct ORM journal-line insertion."""
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, JournalLine):
            continue
        journal = _journal_for_line(session, obj)
        account = _account_for_line(session, obj)
        if journal and account:
            _assert_control_post_allowed(account, source_module=journal.source_module)


def install_control_account_orm_guard() -> None:
    global _orm_guard_installed
    if _orm_guard_installed:
        return
    event.listen(Session, "before_flush", _enforce_orm_control_accounts)
    _orm_guard_installed = True


def _preassign_role_from_kwarg(
    context: AccessContext,
    kwargs: dict,
    key: str,
    role: str,
) -> None:
    account_id = kwargs.get(key)
    if account_id:
        _assign_by_id(context.organisation_id, account_id, role, strict=True)


def _reject_control_bank_account(context: AccessContext, account_id: str | None) -> None:
    if not account_id:
        return
    account = db.session.get(Account, account_id)
    if not account or account.organisation_id != context.organisation_id:
        return
    if control_role(account):
        raise ControlAccountError(
            f"Account {account.code} is a control account and cannot be used as a bank ledger account."
        )


def _wrap_service_method(cls, name: str, roles: tuple[str, ...], before=None) -> None:
    original = getattr(cls, name)
    if getattr(original, "_control_account_guarded", False):
        return

    @wraps(original)
    def guarded(context, *args, **kwargs):
        if before:
            before(context, args, kwargs)
        with _role_scope(*roles):
            return original(context, *args, **kwargs)

    guarded._control_account_guarded = True
    setattr(cls, name, staticmethod(guarded))


def install_control_account_service_guards() -> None:
    """Install trusted subledger scopes and central posting checks."""
    global _service_guards_installed
    if _service_guards_installed:
        return

    from ledgerone.services.ledger import LedgerService
    from ledgerone.modules.banking.services import BankingService
    from ledgerone.modules.expense_claims.services import ExpenseClaimService
    from ledgerone.modules.purchases.credits import PurchaseCreditService
    from ledgerone.modules.purchases.services import PurchasesService
    from ledgerone.modules.sales.credits import SalesCreditService
    from ledgerone.modules.sales.services import SalesService
    from ledgerone.modules.tax.services import TaxService

    original_post_journal = LedgerService.post_journal
    if not getattr(original_post_journal, "_control_account_guarded", False):
        @wraps(original_post_journal)
        def guarded_post_journal(context, *args, **kwargs):
            validate_control_account_lines(
                context,
                kwargs.get("lines") or [],
                source_module=kwargs.get("source_module", "ledger"),
            )
            return original_post_journal(context, *args, **kwargs)

        guarded_post_journal._control_account_guarded = True
        LedgerService.post_journal = staticmethod(guarded_post_journal)

    original_recurring = LedgerService.create_recurring_journal
    if not getattr(original_recurring, "_control_account_guarded", False):
        @wraps(original_recurring)
        def guarded_recurring(context, *args, **kwargs):
            validate_control_account_lines(
                context, kwargs.get("lines") or [], source_module="ledger"
            )
            return original_recurring(context, *args, **kwargs)

        guarded_recurring._control_account_guarded = True
        LedgerService.create_recurring_journal = staticmethod(guarded_recurring)

    original_reverse = LedgerService.reverse_journal
    if not getattr(original_reverse, "_control_account_guarded", False):
        @wraps(original_reverse)
        def guarded_reverse(context, *args, **kwargs):
            with _reversal_scope():
                return original_reverse(context, *args, **kwargs)

        guarded_reverse._control_account_guarded = True
        LedgerService.reverse_journal = staticmethod(guarded_reverse)

    def sales_invoice_before(context, args, kwargs):
        _preassign_role_from_kwarg(context, kwargs, "receivable_account_id", "accounts_receivable")

    def sales_payment_before(context, args, kwargs):
        receivable_id = kwargs.get("receivable_account_id")
        bank_id = kwargs.get("bank_account_id")
        _preassign_role_from_kwarg(context, kwargs, "receivable_account_id", "accounts_receivable")
        _reject_control_bank_account(context, bank_id)
        if bank_id and receivable_id and bank_id == receivable_id:
            raise ControlAccountError("Bank and receivables accounts must be different")

    def purchase_bill_before(context, args, kwargs):
        _preassign_role_from_kwarg(context, kwargs, "payable_account_id", "accounts_payable")

    def purchase_payment_before(context, args, kwargs):
        payable_id = kwargs.get("payable_account_id")
        bank_id = kwargs.get("bank_account_id")
        _preassign_role_from_kwarg(context, kwargs, "payable_account_id", "accounts_payable")
        _reject_control_bank_account(context, bank_id)
        if bank_id and payable_id and bank_id == payable_id:
            raise ControlAccountError("Bank and payables accounts must be different")

    def expense_claim_before(context, args, kwargs):
        account_id = kwargs.get("reimbursement_account_id")
        if account_id:
            _assign_by_id(
                context.organisation_id,
                account_id,
                "employee_reimbursements",
                strict=True,
            )

    _wrap_service_method(
        SalesService, "create_invoice", ("accounts_receivable", "output_vat"), sales_invoice_before
    )
    _wrap_service_method(
        SalesService, "record_payment", ("accounts_receivable",), sales_payment_before
    )
    _wrap_service_method(
        SalesService, "adopt_payment_journal", ("accounts_receivable",), sales_invoice_before
    )
    _wrap_service_method(
        SalesCreditService,
        "create_credit_note",
        ("accounts_receivable", "output_vat"),
    )

    _wrap_service_method(
        PurchasesService, "create_bill", ("accounts_payable", "input_vat"), purchase_bill_before
    )
    _wrap_service_method(
        PurchasesService, "record_payment", ("accounts_payable",), purchase_payment_before
    )
    _wrap_service_method(
        PurchasesService, "adopt_payment_journal", ("accounts_payable",), purchase_bill_before
    )
    _wrap_service_method(
        PurchaseCreditService,
        "create_credit_note",
        ("accounts_payable", "input_vat"),
    )
    _wrap_service_method(
        ExpenseClaimService,
        "create_claim",
        tuple(),
        expense_claim_before,
    )
    _wrap_service_method(
        ExpenseClaimService,
        "approve_and_post",
        ("employee_reimbursements", "input_vat"),
    )

    original_tax_seed = TaxService.seed_defaults
    if not getattr(original_tax_seed, "_control_account_guarded", False):
        @wraps(original_tax_seed)
        def guarded_tax_seed(organisation_id):
            result = original_tax_seed(organisation_id)
            if seed_control_account_metadata_for_org(organisation_id):
                db.session.commit()
            return result

        guarded_tax_seed._control_account_guarded = True
        TaxService.seed_defaults = staticmethod(guarded_tax_seed)

    original_expense_seed = ExpenseClaimService.seed_defaults
    if not getattr(original_expense_seed, "_control_account_guarded", False):
        @wraps(original_expense_seed)
        def guarded_expense_seed(organisation_id):
            result = original_expense_seed(organisation_id)
            if seed_control_account_metadata_for_org(organisation_id):
                db.session.commit()
            return result

        guarded_expense_seed._control_account_guarded = True
        ExpenseClaimService.seed_defaults = staticmethod(guarded_expense_seed)

    original_tax_create = TaxService.create_code
    if not getattr(original_tax_create, "_control_account_guarded", False):
        @wraps(original_tax_create)
        def guarded_tax_create(context, *args, **kwargs):
            row = original_tax_create(context, *args, **kwargs)
            changed = _assign_by_id(
                context.organisation_id, row.sales_tax_account_id, "output_vat", strict=True
            )
            changed = _assign_by_id(
                context.organisation_id, row.purchase_tax_account_id, "input_vat", strict=True
            ) or changed
            if changed:
                db.session.commit()
            return row

        guarded_tax_create._control_account_guarded = True
        TaxService.create_code = staticmethod(guarded_tax_create)

    original_bank_create = BankingService.create_account
    if not getattr(original_bank_create, "_control_account_guarded", False):
        @wraps(original_bank_create)
        def guarded_bank_create(context, *args, **kwargs):
            _reject_control_bank_account(context, kwargs.get("ledger_account_id"))
            return original_bank_create(context, *args, **kwargs)

        guarded_bank_create._control_account_guarded = True
        BankingService.create_account = staticmethod(guarded_bank_create)

    _service_guards_installed = True


def install_control_account_guards() -> None:
    install_control_account_orm_guard()
    install_control_account_service_guards()


class ControlAccountService:
    @staticmethod
    def list_accounts(context: AccessContext):
        if not context.can("ledger.read"):
            raise PermissionError("ledger.read")
        rows = (
            Account.query.filter_by(organisation_id=context.organisation_id)
            .filter(Account.is_control_account.is_(True))
            .order_by(Account.code.asc())
            .all()
        )
        return rows

    @staticmethod
    def post_adjustment(
        context: AccessContext,
        *,
        journal_date: date,
        description: str,
        lines: list[dict],
        reason: str,
        reference: str | None = None,
    ):
        if not context.can("ledger.control_accounts.adjust"):
            raise PermissionError("ledger.control_accounts.adjust")
        reason = (reason or "").strip()
        if not reason:
            raise ControlAccountError("A control-account adjustment requires a reason")
        control_accounts = []
        for raw in lines or []:
            account = db.session.get(Account, raw.get("account_id"))
            if account and account.organisation_id == context.organisation_id and control_role(account):
                control_accounts.append(account)
        if not control_accounts:
            raise ControlAccountError(
                "Use a normal journal for entries that do not affect a control account"
            )

        from ledgerone.services.ledger import LedgerService

        try:
            with _adjustment_scope():
                journal = LedgerService.post_journal(
                    context,
                    journal_date=journal_date,
                    description=(description or "Control-account adjustment").strip()
                    or "Control-account adjustment",
                    lines=lines,
                    reference=(reference or "").strip() or None,
                    source_module="control_adjustment",
                    source_reference=None,
                    metadata={
                        "control_adjustment": True,
                        "control_adjustment_reason": reason,
                        "control_account_ids": sorted({row.id for row in control_accounts}),
                    },
                    commit=False,
                    enforce_permission=False,
                )
            record_audit_event(
                context,
                module_id="ledger",
                action="control_account_adjustment_posted",
                entity_type="journal",
                entity_id=journal.id,
                detail={
                    "reason": reason,
                    "account_ids": sorted({row.id for row in control_accounts}),
                },
            )
            db.session.commit()
            return journal
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _gl_balance(context: AccessContext, account_ids: list[str], role: str, as_of: date) -> Decimal:
        if not account_ids:
            return Decimal("0.00")
        debit, credit = (
            db.session.query(
                db.func.coalesce(db.func.sum(JournalLine.debit), 0),
                db.func.coalesce(db.func.sum(JournalLine.credit), 0),
            )
            .join(Journal, Journal.id == JournalLine.journal_id)
            .filter(
                Journal.organisation_id == context.organisation_id,
                Journal.status == "posted",
                Journal.journal_date <= as_of,
                JournalLine.account_id.in_(account_ids),
            )
            .one()
        )
        debit = _money(debit)
        credit = _money(credit)
        return debit - credit if role in DEBIT_BALANCE_ROLES else credit - debit

    @staticmethod
    def _subledger_balance(context: AccessContext, role: str, as_of: date) -> Decimal:
        if role == "accounts_receivable":
            from ledgerone.modules.sales.models import SalesInvoice, SalesPayment

            invoices = _money(
                db.session.query(db.func.coalesce(db.func.sum(SalesInvoice.total), 0))
                .filter(
                    SalesInvoice.organisation_id == context.organisation_id,
                    SalesInvoice.invoice_date <= as_of,
                    SalesInvoice.posted_journal_id.is_not(None),
                )
                .scalar()
            )
            payments = _money(
                db.session.query(db.func.coalesce(db.func.sum(SalesPayment.amount), 0))
                .filter(
                    SalesPayment.organisation_id == context.organisation_id,
                    SalesPayment.payment_date <= as_of,
                )
                .scalar()
            )
            return invoices - payments

        if role == "accounts_payable":
            from ledgerone.modules.purchases.models import PurchaseBill, PurchasePayment

            bills = _money(
                db.session.query(db.func.coalesce(db.func.sum(PurchaseBill.total), 0))
                .filter(
                    PurchaseBill.organisation_id == context.organisation_id,
                    PurchaseBill.bill_date <= as_of,
                    PurchaseBill.posted_journal_id.is_not(None),
                )
                .scalar()
            )
            payments = _money(
                db.session.query(db.func.coalesce(db.func.sum(PurchasePayment.amount), 0))
                .filter(
                    PurchasePayment.organisation_id == context.organisation_id,
                    PurchasePayment.payment_date <= as_of,
                )
                .scalar()
            )
            return bills - payments

        if role == "output_vat":
            from ledgerone.modules.sales.credit_models import SalesCreditNote
            from ledgerone.modules.sales.models import SalesInvoice

            charged = _money(
                db.session.query(db.func.coalesce(db.func.sum(SalesInvoice.tax_total), 0))
                .filter(
                    SalesInvoice.organisation_id == context.organisation_id,
                    SalesInvoice.invoice_date <= as_of,
                    SalesInvoice.posted_journal_id.is_not(None),
                )
                .scalar()
            )
            credits = _money(
                db.session.query(db.func.coalesce(db.func.sum(SalesCreditNote.tax_total), 0))
                .filter(
                    SalesCreditNote.organisation_id == context.organisation_id,
                    SalesCreditNote.credit_date <= as_of,
                    SalesCreditNote.status == "posted",
                )
                .scalar()
            )
            return charged - credits

        if role == "input_vat":
            from ledgerone.modules.expense_claims.models import ExpenseClaim
            from ledgerone.modules.purchases.credit_models import PurchaseCreditNote
            from ledgerone.modules.purchases.models import PurchaseBill

            bills = _money(
                db.session.query(db.func.coalesce(db.func.sum(PurchaseBill.tax_total), 0))
                .filter(
                    PurchaseBill.organisation_id == context.organisation_id,
                    PurchaseBill.bill_date <= as_of,
                    PurchaseBill.posted_journal_id.is_not(None),
                )
                .scalar()
            )
            credits = _money(
                db.session.query(db.func.coalesce(db.func.sum(PurchaseCreditNote.tax_total), 0))
                .filter(
                    PurchaseCreditNote.organisation_id == context.organisation_id,
                    PurchaseCreditNote.credit_date <= as_of,
                    PurchaseCreditNote.status == "posted",
                )
                .scalar()
            )
            expenses = _money(
                db.session.query(db.func.coalesce(db.func.sum(ExpenseClaim.tax_total), 0))
                .join(Journal, Journal.id == ExpenseClaim.posted_journal_id)
                .filter(
                    ExpenseClaim.organisation_id == context.organisation_id,
                    ExpenseClaim.status == "posted",
                    Journal.journal_date <= as_of,
                )
                .scalar()
            )
            return bills - credits + expenses

        if role == "employee_reimbursements":
            from ledgerone.modules.expense_claims.models import ExpenseClaim

            return _money(
                db.session.query(db.func.coalesce(db.func.sum(ExpenseClaim.total), 0))
                .join(Journal, Journal.id == ExpenseClaim.posted_journal_id)
                .filter(
                    ExpenseClaim.organisation_id == context.organisation_id,
                    ExpenseClaim.status == "posted",
                    Journal.journal_date <= as_of,
                )
                .scalar()
            )

        return Decimal("0.00")

    @staticmethod
    def reconciliation(context: AccessContext, *, as_of: date | None = None):
        if not (context.can("reports.read") or context.can("ledger.read")):
            raise PermissionError("reports.read")
        as_of = as_of or date.today()
        accounts = Account.query.filter_by(organisation_id=context.organisation_id).all()
        rows = []
        for role in (
            "accounts_receivable",
            "accounts_payable",
            "output_vat",
            "input_vat",
            "employee_reimbursements",
        ):
            role_accounts = [row for row in accounts if control_role(row) == role]
            account_ids = [row.id for row in role_accounts]
            ledger_balance = ControlAccountService._gl_balance(
                context, account_ids, role, as_of
            )
            subledger_balance = ControlAccountService._subledger_balance(
                context, role, as_of
            )
            difference = ledger_balance - subledger_balance
            configured = bool(role_accounts)
            rows.append(
                {
                    "role": role,
                    "label": ROLE_LABELS[role],
                    "owner_module": ROLE_OWNER[role],
                    "allowed_modules": sorted(ROLE_ALLOWED_MODULES[role]),
                    "configured": configured,
                    "accounts": [
                        {"id": row.id, "code": row.code, "name": row.name}
                        for row in role_accounts
                    ],
                    "ledger_balance": ledger_balance,
                    "subledger_balance": subledger_balance,
                    "difference": difference,
                    "status": (
                        "unconfigured"
                        if not configured
                        else ("reconciled" if difference == Decimal("0.00") else "difference")
                    ),
                }
            )
        return {
            "as_of": as_of,
            "rows": rows,
            "all_configured_reconciled": all(
                row["status"] == "reconciled"
                for row in rows
                if row["configured"]
            ),
        }
