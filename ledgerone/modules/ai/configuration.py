from __future__ import annotations

from urllib.parse import urlparse

import requests
from flask import current_app

from ledgerone.extensions import db
from ledgerone.models.core import Setting
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


class AIConfiguration:
    """Organisation-level local AI settings with environment-variable fallbacks."""

    SCOPE = "ai"
    KEY = "local_ai"

    @staticmethod
    def defaults() -> dict:
        return {
            "enabled": bool(current_app.config.get("LOCAL_AI_ENABLED", True)),
            "base_url": current_app.config.get("LOCAL_AI_BASE_URL", "http://127.0.0.1:11434"),
            "model": current_app.config.get("LOCAL_AI_MODEL", "qwen3:14b"),
            "timeout": int(current_app.config.get("LOCAL_AI_TIMEOUT", 120)),
            "allow_writes": bool(current_app.config.get("LOCAL_AI_ALLOW_WRITES", True)),
        }

    @classmethod
    def get(cls, organisation_id: str) -> dict:
        config = cls.defaults()
        row = Setting.query.filter_by(
            organisation_id=organisation_id,
            scope=cls.SCOPE,
            key=cls.KEY,
        ).first()
        if row and isinstance(row.value, dict):
            config.update({key: value for key, value in row.value.items() if key in config})
        config["timeout"] = int(config.get("timeout") or 120)
        config["enabled"] = bool(config.get("enabled"))
        config["allow_writes"] = bool(config.get("allow_writes"))
        config["base_url"] = str(config.get("base_url") or "").rstrip("/")
        config["model"] = str(config.get("model") or "").strip()
        return config

    @staticmethod
    def _validate(*, base_url: str, model: str, timeout: int) -> tuple[str, str, int]:
        base_url = (base_url or "").strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AI server URL must be a valid http:// or https:// address")
        model = (model or "").strip()
        if not model:
            raise ValueError("AI model is required")
        timeout = int(timeout)
        if timeout < 5 or timeout > 600:
            raise ValueError("AI timeout must be between 5 and 600 seconds")
        return base_url, model, timeout

    @classmethod
    def update(
        cls,
        context: AccessContext,
        *,
        enabled: bool,
        base_url: str,
        model: str,
        timeout: int,
        allow_writes: bool,
    ) -> dict:
        if not context.can("settings.manage"):
            raise PermissionError("settings.manage")
        before = cls.get(context.organisation_id)
        base_url, model, timeout = cls._validate(
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
        value = {
            "enabled": bool(enabled),
            "base_url": base_url,
            "model": model,
            "timeout": timeout,
            "allow_writes": bool(allow_writes),
        }
        row = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=cls.SCOPE,
            key=cls.KEY,
        ).first()
        if row is None:
            row = Setting(
                organisation_id=context.organisation_id,
                scope=cls.SCOPE,
                key=cls.KEY,
                value=value,
            )
            db.session.add(row)
        else:
            row.value = value
        record_audit_event(
            context,
            module_id="ai",
            action="configuration_updated",
            entity_type="setting",
            entity_id=cls.KEY,
            detail={"before": before, "after": value},
        )
        db.session.commit()
        return value

    @staticmethod
    def probe(*, base_url: str, timeout: int = 3) -> dict:
        base_url = (base_url or "").strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {
                "reachable": False,
                "models": [],
                "base_url": base_url,
                "error": "Invalid AI server URL",
            }
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=max(1, min(int(timeout), 10)))
            response.raise_for_status()
            data = response.json()
            models = sorted(
                item.get("name")
                for item in data.get("models", [])
                if item.get("name")
            )
            return {
                "reachable": True,
                "models": models,
                "base_url": base_url,
            }
        except Exception as exc:
            return {
                "reachable": False,
                "models": [],
                "base_url": base_url,
                "error": str(exc),
            }
