from __future__ import annotations

from ledgerone.extensions import db
from ledgerone.models.core import Setting
from ledgerone.models.ledger import Account
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


SUPPORTED_ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")

DEFAULT_POSTING_ACCOUNT_CODES = {
    "bank": "1000",
    "accounts_receivable": "1200",
    "accounts_payable": "2100",
    "opening_equity": "3000",
    "sales_revenue": "4000",
    "purchase_cost": "5000",
}

POSTING_ROLE_RULES = {
    "accounts_receivable": {"types": {"asset"}, "control_role": "accounts_receivable"},
    "accounts_payable": {"types": {"liability"}, "control_role": "accounts_payable"},
    "sales_revenue": {"types": {"income"}, "non_control": True},
    "purchase_cost": {"types": {"expense", "asset"}, "non_control": True},
    "bank": {"types": {"asset"}, "non_control": True},
    "opening_equity": {"types": {"equity"}, "non_control": True},
}


class PostingAccountError(ValueError):
    pass


class PostingAccountService:
    """Central account classification and posting-role policy."""

    SETTING_SCOPE = "posting_accounts"

    @staticmethod
    def _rule(role: str) -> dict:
        rule = POSTING_ROLE_RULES.get((role or "").strip())
        if not rule:
            raise PostingAccountError(f"Unsupported posting account role: {role}")
        return rule

    @staticmethod
    def _account(context: AccessContext, account_id: str) -> Account:
        account = db.session.get(Account, account_id)
        if not account or account.organisation_id != context.organisation_id:
            raise PostingAccountError("Posting account not found")
        if not account.is_active:
            raise PostingAccountError(f"Account {account.code} is inactive")
        return account

    @staticmethod
    def _has_override(context: AccessContext, account: Account, role: str) -> bool:
        overrides = (account.metadata_json or {}).get("posting_role_overrides") or []
        return role in overrides and context.can("ledger.control_accounts.adjust")

    @staticmethod
    def validate(context: AccessContext, account_id: str, role: str) -> Account:
        rule = PostingAccountService._rule(role)
        account = PostingAccountService._account(context, account_id)
        if rule.get("non_control") and account.is_control_account:
            raise PostingAccountError(
                f"Account {account.code} is not valid for {role}: "
                "control accounts cannot be used for this posting role"
            )
        required_control_role = rule.get("control_role")
        if required_control_role:
            actual = (account.metadata_json or {}).get("control_role")
            if actual != required_control_role:
                raise PostingAccountError(
                    f"Account {account.code} is not valid for {role}: "
                    f"account must have control role {required_control_role}"
                )
        if (
            account.account_type not in rule["types"]
            and not PostingAccountService._has_override(context, account, role)
        ):
            raise PostingAccountError(
                f"Account {account.code} is not valid for {role}: "
                f"account type must be one of {', '.join(sorted(rule['types']))}"
            )
        return account

    @staticmethod
    def seed_defaults(organisation_id: str) -> bool:
        changed = False
        for role, code in DEFAULT_POSTING_ACCOUNT_CODES.items():
            PostingAccountService._rule(role)
            existing = Setting.query.filter_by(
                organisation_id=organisation_id,
                scope=PostingAccountService.SETTING_SCOPE,
                key=role,
            ).first()
            if existing:
                continue
            account = Account.query.filter_by(
                organisation_id=organisation_id,
                code=code,
            ).first()
            if not account:
                continue
            db.session.add(
                Setting(
                    organisation_id=organisation_id,
                    scope=PostingAccountService.SETTING_SCOPE,
                    key=role,
                    value={"account_id": account.id},
                )
            )
            changed = True
        if changed:
            db.session.commit()
        return changed

    @staticmethod
    def default_account_id(organisation_id: str, role: str) -> str | None:
        PostingAccountService._rule(role)
        setting = Setting.query.filter_by(
            organisation_id=organisation_id,
            scope=PostingAccountService.SETTING_SCOPE,
            key=role,
        ).first()
        if not setting:
            return None
        value = setting.value or {}
        return value.get("account_id") if isinstance(value, dict) else None

    @staticmethod
    def resolve(context: AccessContext, role: str, account_id: str | None = None) -> Account:
        effective_id = account_id or PostingAccountService.default_account_id(
            context.organisation_id, role
        )
        if not effective_id:
            raise PostingAccountError(f"No default account is configured for {role}")
        return PostingAccountService.validate(context, effective_id, role)

    @staticmethod
    def configure_default(context: AccessContext, role: str, account_id: str):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        account = PostingAccountService.validate(context, account_id, role)
        setting = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=PostingAccountService.SETTING_SCOPE,
            key=role,
        ).first()
        before = PostingAccountService.default_account_id(context.organisation_id, role)
        if not setting:
            setting = Setting(
                organisation_id=context.organisation_id,
                scope=PostingAccountService.SETTING_SCOPE,
                key=role,
                value={"account_id": account.id},
            )
            db.session.add(setting)
        else:
            setting.value = {"account_id": account.id}
        record_audit_event(
            context,
            module_id="ledger",
            action="default_posting_account_configured",
            entity_type="account",
            entity_id=account.id,
            detail={"role": role, "before_account_id": before, "after_account_id": account.id},
        )
        db.session.commit()
        return account

    @staticmethod
    def set_override(
        context: AccessContext,
        account_id: str,
        role: str,
        *,
        enabled: bool,
        reason: str,
    ) -> Account:
        if not context.can("ledger.control_accounts.adjust"):
            raise PermissionError("ledger.control_accounts.adjust")
        PostingAccountService._rule(role)
        reason = (reason or "").strip()
        if not reason:
            raise PostingAccountError("A posting-role override requires a reason")
        account = PostingAccountService._account(context, account_id)
        metadata = dict(account.metadata_json or {})
        overrides = set(metadata.get("posting_role_overrides") or [])
        if enabled:
            overrides.add(role)
        else:
            overrides.discard(role)
        metadata["posting_role_overrides"] = sorted(overrides)
        account.metadata_json = metadata
        record_audit_event(
            context,
            module_id="ledger",
            action="posting_role_override_enabled" if enabled else "posting_role_override_disabled",
            entity_type="account",
            entity_id=account.id,
            detail={"role": role, "reason": reason},
        )
        db.session.commit()
        return account
