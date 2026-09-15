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

# Install cross-module accounting safeguards after the core model classes are loaded.
# The guard sits below browser/API/AI/module services, so every ORM-backed financial
# posting receives the same base-currency enforcement.
from ledgerone.services.currency import install_currency_guard

install_currency_guard()
