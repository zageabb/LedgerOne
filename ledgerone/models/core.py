from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ledgerone.extensions import db


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    ui_mode = db.Column(db.String(20), nullable=False, default="home")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    memberships = db.relationship("Membership", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Organisation(db.Model):
    __tablename__ = "organisations"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    base_currency = db.Column(db.String(3), nullable=False, default="GBP")
    country_code = db.Column(db.String(2), nullable=False, default="GB")
    fiscal_year_start_month = db.Column(db.Integer, nullable=False, default=4)
    fiscal_year_start_day = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    memberships = db.relationship("Membership", back_populates="organisation", cascade="all, delete-orphan")


class Membership(db.Model):
    __tablename__ = "memberships"
    __table_args__ = (db.UniqueConstraint("organisation_id", "user_id", name="uq_membership_org_user"),)

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(40), nullable=False, default="member")
    permissions = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    organisation = db.relationship("Organisation", back_populates="memberships")
    user = db.relationship("User", back_populates="memberships")


class ApiKey(db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    key_hash = db.Column(db.String(64), nullable=False)
    full_access = db.Column(db.Boolean, nullable=False, default=False)
    permissions = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)

    @staticmethod
    def _hash(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, *, name: str, organisation_id: str | None, full_access: bool = False,
              permissions: list[str] | None = None, created_by_user_id: str | None = None):
        record_id = new_id()
        secret = secrets.token_urlsafe(32)
        token = f"lo_{record_id}_{secret}"
        record = cls(
            id=record_id,
            organisation_id=organisation_id,
            name=name,
            key_hash=cls._hash(secret),
            full_access=full_access,
            permissions=permissions or [],
            created_by_user_id=created_by_user_id,
        )
        return record, token

    def verify_token(self, token: str) -> bool:
        try:
            prefix, token_id, secret = token.split("_", 2)
        except ValueError:
            return False
        if prefix != "lo" or token_id != self.id:
            return False
        return hmac.compare_digest(self.key_hash, self._hash(secret))


class ModuleState(db.Model):
    __tablename__ = "module_states"
    __table_args__ = (db.UniqueConstraint("organisation_id", "module_id", name="uq_module_state_org_module"),)

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    module_id = db.Column(db.String(80), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    settings = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Setting(db.Model):
    __tablename__ = "settings"
    __table_args__ = (db.UniqueConstraint("organisation_id", "scope", "key", name="uq_setting_org_scope_key"),)

    id = db.Column(db.String(36), primary_key=True, default=new_id)
    organisation_id = db.Column(db.String(36), db.ForeignKey("organisations.id"), nullable=False, index=True)
    scope = db.Column(db.String(80), nullable=False, default="general")
    key = db.Column(db.String(120), nullable=False)
    value = db.Column(db.JSON, nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
