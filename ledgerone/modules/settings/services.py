from ledgerone.extensions import db
from ledgerone.models.core import ApiKey, ModuleState, Organisation
from ledgerone.module_registry import module_registry
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class SettingsService:
    @staticmethod
    def organisation(context: AccessContext):
        return db.session.get(Organisation, context.organisation_id)

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
        return state

    @staticmethod
    def list_api_keys(context: AccessContext):
        if not context.can("settings.read"):
            raise PermissionError("settings.read")
        return ApiKey.query.filter_by(
            organisation_id=context.organisation_id
        ).order_by(ApiKey.created_at.desc()).all()

    @staticmethod
    def issue_api_key(context: AccessContext, *, name: str, full_access: bool,
                      permissions: list[str] | None = None):
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        record, token = ApiKey.issue(
            name=name.strip() or "API key",
            organisation_id=context.organisation_id,
            full_access=bool(full_access),
            permissions=permissions or [],
            created_by_user_id=context.user_id,
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
            },
        )
        db.session.commit()
        return record, token

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
