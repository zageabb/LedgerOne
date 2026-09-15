import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    APP_VERSION = os.getenv("LEDGERONE_VERSION", "0.4.0-dev")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'ledgerone.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    ADMIN_EMAIL = os.getenv("LEDGERONE_ADMIN_EMAIL", "admin@ledgerone.local")
    ADMIN_PASSWORD = os.getenv("LEDGERONE_ADMIN_PASSWORD", "change-me-now")
    ADMIN_NAME = os.getenv("LEDGERONE_ADMIN_NAME", "LedgerOne Administrator")
    DEFAULT_ORG_NAME = os.getenv("LEDGERONE_ORG_NAME", "My Ledger")

    LOCAL_AI_ENABLED = _env_bool("LOCAL_AI_ENABLED", True)
    LOCAL_AI_BASE_URL = os.getenv("LOCAL_AI_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    LOCAL_AI_MODEL = os.getenv("LOCAL_AI_MODEL", "qwen3:14b")
    LOCAL_AI_TIMEOUT = int(os.getenv("LOCAL_AI_TIMEOUT", "120"))
    LOCAL_AI_ALLOW_WRITES = _env_bool("LOCAL_AI_ALLOW_WRITES", True)
    KNOWLEDGE_MAX_BYTES = int(os.getenv("LEDGERONE_KNOWLEDGE_MAX_BYTES", str(10 * 1024 * 1024)))

    DOCUMENT_STORAGE_DIR = os.getenv(
        "LEDGERONE_DOCUMENT_STORAGE_DIR", str(BASE_DIR / "data" / "documents")
    )
    DOCUMENT_MAX_BYTES = int(os.getenv("LEDGERONE_DOCUMENT_MAX_BYTES", str(25 * 1024 * 1024)))

    # Scheduled transactions may be generated automatically, but generation only creates
    # workflow work items. Ledger posting is always a separate explicit action.
    WORKFLOW_AUTO_GENERATE_DUE = _env_bool("LEDGERONE_WORKFLOW_AUTO_GENERATE_DUE", True)

    # Development/home installations can opt into strict posting periods. Production
    # defaults to requiring a defined period for every posting date.
    ACCOUNTING_PERIOD_POLICY = os.getenv("LEDGERONE_ACCOUNTING_PERIOD_POLICY", "optional").strip().lower()

    # Development and single-user installs can auto-create an empty schema. Production
    # defaults to Alembic/Flask-Migrate so schema changes are explicit and repeatable.
    AUTO_CREATE_SCHEMA = _env_bool("AUTO_CREATE_SCHEMA", True)
    AUTO_SEED_DEFAULTS = _env_bool("AUTO_SEED_DEFAULTS", True)

    # Cookies are shared across ports on a host; isolate LedgerOne from other apps.
    SESSION_COOKIE_NAME = "ledgerone_session"
    REMEMBER_COOKIE_NAME = "ledgerone_remember"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30

    # Browser forms are protected explicitly; API routes rely on auth tokens/session.
    WTF_CSRF_CHECK_DEFAULT = False


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    AUTO_CREATE_SCHEMA = _env_bool("AUTO_CREATE_SCHEMA", False)
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    ACCOUNTING_PERIOD_POLICY = os.getenv("LEDGERONE_ACCOUNTING_PERIOD_POLICY", "required").strip().lower()


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    return ProductionConfig if env == "production" else DevelopmentConfig
