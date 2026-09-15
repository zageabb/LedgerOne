from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import ApiKey, Membership, ModuleState, Organisation, Setting, User
from ledgerone.models.ledger import (
    Account,
    AccountingPeriod,
    Journal,
    JournalLine,
    OpeningBalanceBatch,
    RecurringJournal,
    RecurringJournalRun,
)

__all__ = [
    "AuditEvent",
    "ApiKey",
    "Membership",
    "ModuleState",
    "Organisation",
    "Setting",
    "User",
    "Account",
    "AccountingPeriod",
    "Journal",
    "JournalLine",
    "OpeningBalanceBatch",
    "RecurringJournal",
    "RecurringJournalRun",
]

# Install model-level accounting safeguards while model modules are initialising.
# Service wrappers are installed by create_app after model imports are complete, which
# keeps standalone LedgerService imports free of circular dependencies.
from ledgerone.services.control_accounts import install_control_account_orm_guard
from ledgerone.services.currency import install_currency_orm_guard

install_currency_orm_guard()
install_control_account_orm_guard()
