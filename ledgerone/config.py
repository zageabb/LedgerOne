import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
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

    LOCAL_AI_ENABLED = os.getenv("LOCAL_AI_ENABLED", "true").lower() in {"1", "true", "yes"}
    LOCAL_AI_BASE_URL = os.getenv("LOCAL_AI_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    LOCAL_AI_MODEL = os.getenv("LOCAL_AI_MODEL", "qwen3:14b")
    LOCAL_AI_TIMEOUT = int(os.getenv("LOCAL_AI_TIMEOUT", "120"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    return ProductionConfig if env == "production" else DevelopmentConfig
