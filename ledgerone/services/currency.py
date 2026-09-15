from __future__ import annotations

from functools import wraps

from sqlalchemy import event
from sqlalchemy.orm import Session

from ledgerone.extensions import db
from ledgerone.models.core import Organisation
from ledgerone.models.ledger import Account, Journal, JournalLine


class CurrencyPolicyError(ValueError):
    """Raised when a transaction would require unsupported FX accounting."""


# Payment rows can also be created by adopting an existing journal, so they need their
# own subledger guard in addition to the central journal-posting check.
_DIRECT_CURRENCY_TABLES = {"sales_payments", "purchase_payments"}

_installed = False


def _normalise(currency: str | None) -> str | None:
    value = (currency or "").strip().upper()
    return value[:3] if value else None


def organisation_base_currency(context) -> str:
    if not context or not context.organisation_id:
        raise CurrencyPolicyError("An organisation is required for currency validation")
    organisation = db.session.get(Organisation, context.organisation_id)
    if not organisation:
        raise CurrencyPolicyError("Organisation not found for currency validation")
    return _normalise(organisation.base_currency) or "GBP"


def _assert_supported(base_currency: str, currency: str | None, *, label: str) -> str:
    candidate = _normalise(currency) or base_currency
    if candidate != base_currency:
        raise CurrencyPolicyError(
            "Multi-currency accounting is not yet enabled for this organisation. "
            f"{label} uses {candidate}, but the organisation base currency is {base_currency}."
        )
    return candidate


def validate_journal_lines(context, lines: list[dict] | None) -> str:
    """Validate raw journal lines before LedgerService adds any accounting records.

    This is the normal enforcement path used by browser, API, business modules and AI.
    It deliberately treats a missing line currency as the organisation base currency and
    rejects ``foreign_amount`` until a real FX/base-amount/revaluation model exists.
    """
    base = organisation_base_currency(context)
    for index, raw in enumerate(lines or [], start=1):
        if raw.get("foreign_amount") is not None:
            raise CurrencyPolicyError(
                "Foreign-currency amounts are disabled until LedgerOne has a complete "
                "exchange-rate and revaluation model."
            )
        raw["currency"] = _assert_supported(
            base,
            raw.get("currency"),
            label=f"Journal line {index}",
        )
        account_id = raw.get("account_id")
        if account_id:
            account = db.session.get(Account, account_id)
            if account and account.organisation_id == context.organisation_id:
                _assert_supported(base, account.currency, label=f"Account {account.code}")
    return base


def _organisation(session: Session, organisation_id: str | None, cache: dict[str, Organisation]) -> Organisation:
    if not organisation_id:
        raise CurrencyPolicyError("An organisation is required for currency validation")
    if organisation_id in cache:
        return cache[organisation_id]
    for candidate in session.new:
        if isinstance(candidate, Organisation) and candidate.id == organisation_id:
            cache[organisation_id] = candidate
            return candidate
    row = session.get(Organisation, organisation_id)
    if not row:
        raise CurrencyPolicyError("Organisation not found for currency validation")
    cache[organisation_id] = row
    return row


def _base_currency(session: Session, organisation_id: str | None, cache: dict[str, Organisation]) -> str:
    return _normalise(_organisation(session, organisation_id, cache).base_currency) or "GBP"


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


def _is_controlled_reversal(session: Session, journal: Journal) -> bool:
    """Allow genuine reversals of historic FX data so bad legacy entries can be removed."""
    if not journal.reversal_of_id:
        return False
    original = session.get(Journal, journal.reversal_of_id)
    return bool(
        original
        and original.organisation_id == journal.organisation_id
        and journal.source_module == "ledger"
        and journal.source_reference == original.id
        and (journal.metadata_json or {}).get("reversal_of") == original.id
    )


def _validate_direct_payment(
    session: Session,
    obj,
    organisation_cache: dict[str, Organisation],
) -> None:
    base = _base_currency(session, getattr(obj, "organisation_id", None), organisation_cache)
    obj.currency = _assert_supported(
        base,
        getattr(obj, "currency", None),
        label=obj.__tablename__.replace("_", " ").rstrip("s").capitalize(),
    )


def _validate_journal_line(
    session: Session,
    line: JournalLine,
    organisation_cache: dict[str, Organisation],
) -> None:
    journal = _journal_for_line(session, line)
    if not journal:
        return
    if _is_controlled_reversal(session, journal):
        return

    base = _base_currency(session, journal.organisation_id, organisation_cache)
    if line.foreign_amount is not None:
        raise CurrencyPolicyError(
            "Foreign-currency amounts are disabled until LedgerOne has a complete "
            "exchange-rate and revaluation model."
        )
    line.currency = _assert_supported(base, line.currency, label="Journal line")
    account = _account_for_line(session, line)
    if account:
        _assert_supported(base, account.currency, label=f"Account {account.code}")


def _enforce_orm_base_currency(session: Session, flush_context, instances) -> None:
    """Defence-in-depth for code that writes models without LedgerService."""
    organisation_cache: dict[str, Organisation] = {}
    for obj in list(session.new) + list(session.dirty):
        table_name = getattr(obj, "__tablename__", None)
        if table_name in _DIRECT_CURRENCY_TABLES:
            _validate_direct_payment(session, obj, organisation_cache)
        elif isinstance(obj, JournalLine):
            _validate_journal_line(session, obj, organisation_cache)


def _install_service_guards() -> None:
    # Import here to avoid a models -> currency -> ledger-service import cycle while the
    # model package is still initialising.
    from ledgerone.services.ledger import LedgerService

    if not getattr(LedgerService.post_journal, "_base_currency_guarded", False):
        original_post_journal = LedgerService.post_journal

        @wraps(original_post_journal)
        def guarded_post_journal(context, *args, **kwargs):
            # A genuine reversal may need to mirror historic unsupported currency values;
            # the ORM guard independently verifies that it has the controlled reversal shape.
            if not kwargs.get("reversal_of_id"):
                validate_journal_lines(context, kwargs.get("lines") or [])
            return original_post_journal(context, *args, **kwargs)

        guarded_post_journal._base_currency_guarded = True
        LedgerService.post_journal = staticmethod(guarded_post_journal)

    if not getattr(LedgerService.create_recurring_journal, "_base_currency_guarded", False):
        original_create_recurring = LedgerService.create_recurring_journal

        @wraps(original_create_recurring)
        def guarded_create_recurring(context, *args, **kwargs):
            validate_journal_lines(context, kwargs.get("lines") or [])
            return original_create_recurring(context, *args, **kwargs)

        guarded_create_recurring._base_currency_guarded = True
        LedgerService.create_recurring_journal = staticmethod(guarded_create_recurring)


def install_currency_guard() -> None:
    """Install central service and ORM base-currency enforcement exactly once."""
    global _installed
    if _installed:
        return
    _install_service_guards()
    event.listen(Session, "before_flush", _enforce_orm_base_currency)
    _installed = True
