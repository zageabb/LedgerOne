from __future__ import annotations

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, Setting
from ledgerone.modules.tax.models import TaxProfile
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class OrganisationProfileService:
    """Organisation legal/contact identity used on customer-facing documents.

    Legal identity data is deliberately stored in the existing organisation-scoped
    settings table. VAT registration remains owned by TaxProfile so there is only
    one source of truth for the tax registration number and VAT status.
    """

    SCOPE = "organisation_profile"
    FIELDS = (
        "registered_name",
        "trading_name",
        "company_number",
        "email",
        "phone",
        "website",
        "address",
    )

    @staticmethod
    def _setting_rows(organisation_id: str) -> dict[str, Setting]:
        return {
            row.key: row
            for row in Setting.query.filter_by(
                organisation_id=organisation_id,
                scope=OrganisationProfileService.SCOPE,
            ).all()
        }

    @staticmethod
    def get(organisation_id: str) -> dict:
        organisation = db.session.get(Organisation, organisation_id)
        if not organisation:
            raise ValueError("Organisation not found")

        rows = OrganisationProfileService._setting_rows(organisation_id)
        values = {
            key: (rows[key].value if key in rows else None)
            for key in OrganisationProfileService.FIELDS
        }
        values["registered_name"] = (
            str(values.get("registered_name") or "").strip() or organisation.name
        )
        values["trading_name"] = str(values.get("trading_name") or "").strip() or None
        values["company_number"] = str(values.get("company_number") or "").strip() or None
        values["email"] = str(values.get("email") or "").strip() or None
        values["phone"] = str(values.get("phone") or "").strip() or None
        values["website"] = str(values.get("website") or "").strip() or None
        values["address"] = values.get("address") if isinstance(values.get("address"), dict) else {}

        tax_profile = TaxProfile.query.filter_by(organisation_id=organisation_id).first()
        values["is_vat_registered"] = bool(tax_profile and tax_profile.is_vat_registered)
        values["vat_registration_number"] = (
            (tax_profile.registration_number or "").strip()
            if tax_profile and tax_profile.registration_number
            else None
        )
        values["vat_jurisdiction"] = tax_profile.jurisdiction if tax_profile else None
        return values

    @staticmethod
    def update(
        context: AccessContext,
        *,
        registered_name: str,
        trading_name: str | None = None,
        company_number: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        website: str | None = None,
        address_line1: str | None = None,
        address_line2: str | None = None,
        city: str | None = None,
        county: str | None = None,
        postcode: str | None = None,
        country: str | None = None,
    ) -> dict:
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")

        organisation = db.session.get(Organisation, context.organisation_id)
        if not organisation:
            raise ValueError("Organisation not found")

        registered_name = (registered_name or "").strip()
        if not registered_name:
            raise ValueError("Registered/legal name is required")

        address = {
            "line1": (address_line1 or "").strip(),
            "line2": (address_line2 or "").strip(),
            "city": (city or "").strip(),
            "county": (county or "").strip(),
            "postcode": (postcode or "").strip(),
            "country": (country or "").strip(),
        }
        address = {key: value for key, value in address.items() if value}

        after = {
            "registered_name": registered_name,
            "trading_name": (trading_name or "").strip() or None,
            "company_number": (company_number or "").strip() or None,
            "email": (email or "").strip() or None,
            "phone": (phone or "").strip() or None,
            "website": (website or "").strip() or None,
            "address": address,
        }
        before = OrganisationProfileService.get(context.organisation_id)
        rows = OrganisationProfileService._setting_rows(context.organisation_id)

        for key, value in after.items():
            row = rows.get(key)
            if row is None:
                row = Setting(
                    organisation_id=context.organisation_id,
                    scope=OrganisationProfileService.SCOPE,
                    key=key,
                )
                db.session.add(row)
            row.value = value

        record_audit_event(
            context,
            module_id="organisation_profile",
            action="organisation_profile_updated",
            entity_type="organisation",
            entity_id=organisation.id,
            detail={
                "before": {key: before.get(key) for key in after},
                "after": after,
            },
        )
        db.session.commit()
        return OrganisationProfileService.get(context.organisation_id)

    @staticmethod
    def address_lines(profile: dict) -> list[str]:
        address = profile.get("address") if isinstance(profile, dict) else {}
        if not isinstance(address, dict):
            return []
        return [
            str(address.get(key) or "").strip()
            for key in ("line1", "line2", "city", "county", "postcode", "country")
            if str(address.get(key) or "").strip()
        ]

    @staticmethod
    def vat_invoice_readiness(organisation_id: str, *, customer_address=None) -> list[str]:
        """Return human-readable gaps that would make a UK VAT invoice incomplete."""
        profile = OrganisationProfileService.get(organisation_id)
        missing: list[str] = []
        if not profile.get("registered_name"):
            missing.append("supplier registered/legal name")
        if not OrganisationProfileService.address_lines(profile):
            missing.append("supplier address")
        if not profile.get("vat_registration_number"):
            missing.append("supplier VAT registration number")
        if not customer_address or not any(str(value or "").strip() for value in customer_address.values()):
            missing.append("customer address")
        return missing
