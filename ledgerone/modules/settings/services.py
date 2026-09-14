from __future__ import annotations

from datetime import datetime, timezone

from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, Membership, ModuleState, Organisation, User
from ledgerone.module_registry import module_registry
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class SettingsService:
    @staticmethod
    def organisation(context: AccessContext):
        return db.session.get(Organisation, context.organisation_id)

    @staticmethod
    def permission_catalog():
        permissions = set()
        for manifest in module_registry.manifests:
            permissions.update(manifest.permissions or ())
        return sorted(permissions)

    @staticmethod
    def update_organisation(context: AccessContext, *, name: str, base_currency: str,
                            country_code: str, fiscal_year_start_month: int,
                            fiscal_year_start_day: int):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        org = SettingsService.organisation(context)
        if not org:
            raise ValueError("Organisation not found")
        before = {
            "name": org.name,
            "base_currency": org.base_currency,
            "country_code": org.country_code,
            "fiscal_year_start_month": org.fiscal_year_start_month,
            "fiscal_year_start_day": org.fiscal_year_start_day,
        }
        org.name = name.strip() or org.name
        org.base_currency = (base_currency or "GBP").upper()[:3]
        org.country_code = (country_code or "GB").upper()[:2]
        org.fiscal_year_start_month = max(1, min(int(fiscal_year_start_month), 12))
        org.fiscal_year_start_day = max(1, min(int(fiscal_year_start_day), 31))
        after = {
            "name": org.name,
            "base_currency": org.base_currency,
            "country_code": org.country_code,
            "fiscal_year_start_month": org.fiscal_year_start_month,
            "fiscal_year_start_day": org.fiscal_year_start_day,
        }
        record_audit_event(
            context,
            module_id="settings",
            action="organisation_updated",
            entity_type="organisation",
            entity_id=org.id,
            detail={"before": before, "after": after},
        )
        db.session.commit()
        return org

    @staticmethod
    def module_states(context: AccessContext):
        results = []
        for manifest in module_registry.manifests:
            state = ModuleState.query.filter_by(
                organisation_id=context.organisation_id, module_id=manifest.id
            ).first()
            results.append(
                {
                    "manifest": manifest,
                    "enabled": True if manifest.always_on else (
                        state.enabled if state else manifest.default_enabled
                    ),
                }
            )
        return results

    @staticmethod
    def set_module_enabled(context: AccessContext, module_id: str, enabled: bool):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        manifest = module_registry.get(module_id)
        if not manifest:
            raise ValueError("Unknown module")
        if manifest.always_on and not enabled:
            raise ValueError(f"{manifest.name} is a core module and cannot be disabled")
        if enabled:
            missing = [
                dep for dep in manifest.dependencies
                if not module_registry.is_enabled(context.organisation_id, dep)
            ]
            if missing:
                raise ValueError(f"Enable dependencies first: {', '.join(missing)}")
        else:
            dependants = [
                item.id for item in module_registry.manifests
                if module_id in item.dependencies
                and module_registry.is_enabled(context.organisation_id, item.id)
            ]
            if dependants:
                raise ValueError(
                    f"Disable dependent modules first: {', '.join(dependants)}"
                )
        state = ModuleState.query.filter_by(
            organisation_id=context.organisation_id, module_id=module_id
        ).first()
        before = True if manifest.always_on else (
            state.enabled if state else manifest.default_enabled
        )
        if not state:
            state = ModuleState(
                organisation_id=context.organisation_id,
                module_id=module_id,
                enabled=enabled,
            )
            db.session.add(state)
        else:
            state.enabled = enabled
        record_audit_event(
            context,
            module_id="settings",
            action="module_enabled" if enabled else "module_disabled",
            entity_type="module",
            entity_id=module_id,
            detail={"name": manifest.name, "before": before, "after": bool(enabled)},
        )
        db.session.commit()
        if enabled:
            module_registry.seed_module_defaults(context.organisation_id, module_id)
        return state

    @staticmethod
    def list_members(context: AccessContext):
        if not context.can("settings.read"):
            raise PermissionError("settings.read")
        return (
            Membership.query.filter_by(organisation_id=context.organisation_id)
            .join(User)
            .order_by(Membership.is_active.desc(), User.name.asc(), User.email.asc())
            .all()
        )

    @staticmethod
    def _last_owner_guard(membership: Membership, *, new_role: str | None = None,
                          new_active: bool | None = None):
        resulting_role = new_role if new_role is not None else membership.role
        resulting_active = new_active if new_active is not None else membership.is_active
        if membership.role != "owner" or not membership.is_active:
            return
        if resulting_role == "owner" and resulting_active:
            return
        owners = Membership.query.filter_by(
            organisation_id=membership.organisation_id,
            role="owner",
            is_active=True,
        ).count()
        if owners <= 1:
            raise ValueError("The organisation must keep at least one active owner")

    @staticmethod
    def save_member(
        context: AccessContext,
        *,
        email: str,
        name: str,
        role: str,
        permissions: list[str] | None = None,
        password: str | None = None,
        active: bool = True,
    ):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        email = (email or "").strip().lower()
        name = (name or "").strip()
        role = (role or "member").strip().lower()
        if not email or "@" not in email:
            raise ValueError("A valid email address is required")
        if not name:
            raise ValueError("Member name is required")
        if role not in {"owner", "admin", "member", "viewer"}:
            raise ValueError("Role must be owner, admin, member or viewer")

        allowed = set(SettingsService.permission_catalog())
        requested = sorted({item for item in (permissions or []) if item in allowed})
        if role == "viewer":
            requested = sorted(
                permission for permission in allowed
                if permission.endswith(".read") or permission in {"ai.use"}
            )
        elif role in {"owner", "admin"}:
            requested = []

        user = User.query.filter_by(email=email).first()
        created_user = False
        if user is None:
            if not password or len(password) < 8:
                raise ValueError("A new member needs a temporary password of at least 8 characters")
            user = User(email=email, name=name, ui_mode="home")
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            created_user = True
        else:
            user.name = name
            if password:
                if len(password) < 8:
                    raise ValueError("Password must be at least 8 characters")
                user.set_password(password)

        membership = Membership.query.filter_by(
            organisation_id=context.organisation_id,
            user_id=user.id,
        ).first()
        before = None
        if membership is None:
            membership = Membership(
                organisation_id=context.organisation_id,
                user_id=user.id,
                role=role,
                permissions=requested,
                is_active=bool(active),
            )
            db.session.add(membership)
        else:
            before = {
                "role": membership.role,
                "permissions": list(membership.permissions or []),
                "is_active": membership.is_active,
            }
            SettingsService._last_owner_guard(
                membership,
                new_role=role,
                new_active=bool(active),
            )
            membership.role = role
            membership.permissions = requested
            membership.is_active = bool(active)

        db.session.flush()
        record_audit_event(
            context,
            module_id="settings",
            action="member_created" if before is None else "member_updated",
            entity_type="membership",
            entity_id=membership.id,
            detail={
                "email": email,
                "name": name,
                "created_user": created_user,
                "before": before,
                "after": {
                    "role": membership.role,
                    "permissions": list(membership.permissions or []),
                    "is_active": membership.is_active,
                },
            },
        )
        db.session.commit()
        return membership

    @staticmethod
    def deactivate_member(context: AccessContext, membership_id: str):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        membership = db.session.get(Membership, membership_id)
        if not membership or membership.organisation_id != context.organisation_id:
            raise ValueError("Member not found")
        if membership.user_id == context.user_id:
            raise ValueError("You cannot deactivate your own current membership")
        SettingsService._last_owner_guard(membership, new_active=False)
        membership.is_active = False
        record_audit_event(
            context,
            module_id="settings",
            action="member_deactivated",
            entity_type="membership",
            entity_id=membership.id,
            detail={"user_id": membership.user_id, "role": membership.role},
        )
        db.session.commit()
        return membership

    @staticmethod
    def list_api_keys(context: AccessContext):
        if not context.can("settings.read"):
            raise PermissionError("settings.read")
        return ApiKey.query.filter_by(
            organisation_id=context.organisation_id
        ).order_by(ApiKey.created_at.desc()).all()

    @staticmethod
    def issue_api_key(
        context: AccessContext,
        *,
        name: str,
        full_access: bool,
        permissions: list[str] | None = None,
        expires_at: datetime | None = None,
    ):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise ValueError("API key expiry must be in the future")
        record, token = ApiKey.issue(
            name=name.strip() or "API key",
            organisation_id=context.organisation_id,
            full_access=bool(full_access),
            permissions=permissions or [],
            created_by_user_id=context.user_id,
            expires_at=expires_at,
        )
        db.session.add(record)
        db.session.flush()
        record_audit_event(
            context,
            module_id="settings",
            action="api_key_created",
            entity_type="api_key",
            entity_id=record.id,
            detail={
                "name": record.name,
                "full_access": record.full_access,
                "permissions": list(record.permissions or []),
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            },
        )
        db.session.commit()
        return record, token

    @staticmethod
    def rotate_api_key(context: AccessContext, key_id: str, *, expires_at: datetime | None = None):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        old = db.session.get(ApiKey, key_id)
        if not old or old.organisation_id != context.organisation_id:
            raise ValueError("API key not found")
        if not old.is_active:
            raise ValueError("Only an active API key can be rotated")
        effective_expiry = expires_at if expires_at is not None else old.expires_at
        if effective_expiry is not None and effective_expiry.tzinfo is None:
            effective_expiry = effective_expiry.replace(tzinfo=timezone.utc)
        if effective_expiry is not None and effective_expiry <= datetime.now(timezone.utc):
            raise ValueError("API key expiry must be in the future")
        replacement, token = ApiKey.issue(
            name=old.name,
            organisation_id=old.organisation_id,
            full_access=old.full_access,
            permissions=list(old.permissions or []),
            created_by_user_id=context.user_id,
            expires_at=effective_expiry,
        )
        old.is_active = False
        db.session.add(replacement)
        db.session.flush()
        record_audit_event(
            context,
            module_id="settings",
            action="api_key_rotated",
            entity_type="api_key",
            entity_id=replacement.id,
            detail={"replaces": old.id, "name": old.name},
        )
        db.session.commit()
        return replacement, token

    @staticmethod
    def revoke_api_key(context: AccessContext, key_id: str):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        record = db.session.get(ApiKey, key_id)
        if not record or record.organisation_id != context.organisation_id:
            raise ValueError("API key not found")
        record.is_active = False
        record_audit_event(
            context,
            module_id="settings",
            action="api_key_revoked",
            entity_type="api_key",
            entity_id=record.id,
            detail={"name": record.name},
        )
        db.session.commit()
        return record
