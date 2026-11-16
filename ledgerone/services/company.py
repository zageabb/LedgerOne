"""Company administration. Organisations remain the accounting/security boundary."""
import re

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation
from ledgerone.services.audit import record_audit_event


class CompanyService:
    @staticmethod
    def _code(value):
        code = (value or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,19}", code):
            raise ValueError("Company code must contain 2-20 letters, digits, _ or -")
        return code

    @staticmethod
    def _address(value):
        if not isinstance(value, dict):
            raise ValueError("Registered address must be an object")
        allowed = {"line1", "line2", "city", "county", "postcode", "country"}
        if set(value) - allowed or any(not isinstance(v, str) or len(v) > 255 for v in value.values()):
            raise ValueError("Invalid registered address")
        return {k: v.strip() for k, v in value.items() if v.strip()}

    @staticmethod
    def update(context, *, company_code, trading_name="", registration_number="", vat_number="",
               registered_address=None):
        if not context.can("settings.manage") or not context.organisation_id:
            raise PermissionError("settings.manage")
        org = db.session.get(Organisation, context.organisation_id)
        if not org or not org.is_active:
            raise ValueError("Company unavailable")
        code = CompanyService._code(company_code)
        existing = Organisation.query.filter_by(company_code=code).first()
        if existing and existing.id != org.id:
            raise ValueError("Company code is already allocated")
        before = {k: getattr(org, k) for k in
                  ("company_code", "trading_name", "registration_number", "vat_number", "registered_address")}
        org.company_code = code
        org.trading_name = (trading_name or "").strip()[:255] or None
        org.registration_number = (registration_number or "").strip()[:60] or None
        org.vat_number = (vat_number or "").strip()[:60] or None
        org.registered_address = CompanyService._address(registered_address or {})
        record_audit_event(context, module_id="settings", action="company_profile_updated",
                           entity_type="organisation", entity_id=org.id,
                           detail={"before": before, "after": {
                               k: getattr(org, k) for k in before}})
        db.session.commit()
        return org

    @staticmethod
    def create(context, *, name, company_code):
        # Company creation is a privileged owner operation, not a way for regular
        # members to grant themselves unrestricted access to another ledger.
        if not context.user_id or not context.organisation_id:
            raise PermissionError("A company owner is required")
        owner = Membership.query.filter_by(user_id=context.user_id,
                                           organisation_id=context.organisation_id,
                                           role="owner", is_active=True).first()
        if not owner:
            raise PermissionError("Only company owners can create companies")
        clean_name = (name or "").strip()
        code = CompanyService._code(company_code)
        if not clean_name or len(clean_name) > 255:
            raise ValueError("Company name must be 1-255 characters")
        if Organisation.query.filter_by(company_code=code).first():
            raise ValueError("Company code is already allocated")
        from ledgerone.bootstrap import _seed_chart, _ensure_control_metadata_once
        from ledgerone.module_registry import module_registry
        from ledgerone.services.account_roles import PostingAccountService

        org = Organisation(name=clean_name, company_code=code,
                           slug="company-" + code.lower())
        db.session.add(org)
        db.session.flush()
        db.session.add(Membership(user_id=context.user_id, organisation_id=org.id,
                                  role="owner", permissions=["*"]))
        record_audit_event(context, module_id="settings", action="company_created",
                           entity_type="organisation", entity_id=org.id,
                           detail={"name": clean_name, "company_code": code})
        db.session.commit()
        module_registry.ensure_org_states(org.id)
        fresh = _seed_chart(org.id)
        module_registry.seed_org_defaults(org.id)
        _ensure_control_metadata_once(org.id, fresh_chart=fresh)
        PostingAccountService.seed_defaults(org.id)
        return org
