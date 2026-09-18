from ledgerone.extensions import db
from ledgerone.models.core import new_id, utcnow


class TaxProfile(db.Model):
    __tablename__ = "tax_profiles"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", name="uq_tax_profile_organisation"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(
        db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True
    )
    jurisdiction = db.Column(db.String(10), nullable=False, default="GB")
    is_vat_registered = db.Column(db.Boolean, nullable=False, default=False)
    registration_number = db.Column(db.String(80), nullable=True)
    scheme = db.Column(db.String(40), nullable=False, default="standard")
    return_frequency = db.Column(db.String(20), nullable=False, default="quarterly")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class TaxCode(db.Model):
    __tablename__ = "tax_codes"
    __table_args__ = (
        db.UniqueConstraint("organisation_id", "code", name="uq_tax_code_org_code"),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(
        db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True
    )
    code = db.Column(db.String(40), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    rate_percent = db.Column(db.Numeric(7, 4), nullable=False, default=0)
    treatment = db.Column(db.String(30), nullable=False, default="standard", index=True)
    scope = db.Column(db.String(20), nullable=False, default="both", index=True)
    sales_tax_account_id = db.Column(
        db.String(36), db.ForeignKey("accounts.id"), nullable=True, index=True
    )
    purchase_tax_account_id = db.Column(
        db.String(36), db.ForeignKey("accounts.id"), nullable=True, index=True
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    sales_tax_account = db.relationship("Account", foreign_keys=[sales_tax_account_id])
    purchase_tax_account = db.relationship("Account", foreign_keys=[purchase_tax_account_id])


class VATReturnPeriod(db.Model):
    __tablename__ = "vat_return_periods"
    __table_args__ = (
        db.UniqueConstraint(
            "organisation_id", "start_date", "end_date", name="uq_vat_return_period_org_dates"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(
        db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True
    )
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    snapshot_json = db.Column(db.JSON, nullable=False, default=dict)
    finalised_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    finalised_at = db.Column(db.DateTime(timezone=True), nullable=True)
    submitted_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    submission_reference = db.Column(db.String(160), nullable=True)
    submission_note = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    adjustments = db.relationship(
        "VATAdjustment", back_populates="return_period", lazy="selectin"
    )


class VATAdjustment(db.Model):
    __tablename__ = "vat_adjustments"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(
        db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True
    )
    tax_point = db.Column(db.Date, nullable=False, index=True)
    box_number = db.Column(db.String(2), nullable=False, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    evidence_reference = db.Column(db.String(500), nullable=True)
    return_period_id = db.Column(
        db.String(36), db.ForeignKey("vat_return_periods.id"), nullable=True, index=True
    )
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    return_period = db.relationship("VATReturnPeriod", back_populates="adjustments")
