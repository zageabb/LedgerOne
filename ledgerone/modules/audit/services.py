from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_

from ledgerone.models.audit import AuditEvent
from ledgerone.services.context import AccessContext


class AuditService:
    @staticmethod
    def _base_query(context: AccessContext):
        if not context.organisation_id:
            raise ValueError("An organisation is required")
        return AuditEvent.query.filter(AuditEvent.organisation_id == context.organisation_id)

    @staticmethod
    def search(
        context: AccessContext,
        *,
        module_id: str | None = None,
        action: str | None = None,
        actor_type: str | None = None,
        entity_type: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        text: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        if not context.can("audit.read"):
            raise PermissionError("audit.read")
        query = AuditService._base_query(context)
        if module_id:
            query = query.filter(AuditEvent.module_id == module_id)
        if action:
            query = query.filter(AuditEvent.action == action)
        if actor_type:
            query = query.filter(AuditEvent.actor_type == actor_type)
        if entity_type:
            query = query.filter(AuditEvent.entity_type == entity_type)
        if from_date:
            query = query.filter(AuditEvent.created_at >= datetime.combine(from_date, time.min))
        if to_date:
            query = query.filter(
                AuditEvent.created_at < datetime.combine(to_date + timedelta(days=1), time.min)
            )
        if text:
            pattern = f"%{text.strip()}%"
            query = query.filter(
                or_(
                    AuditEvent.module_id.ilike(pattern),
                    AuditEvent.action.ilike(pattern),
                    AuditEvent.actor_type.ilike(pattern),
                    AuditEvent.actor_id.ilike(pattern),
                    AuditEvent.entity_type.ilike(pattern),
                    AuditEvent.entity_id.ilike(pattern),
                )
            )
        total = query.count()
        rows = (
            query.order_by(AuditEvent.created_at.desc())
            .offset(max(0, int(offset)))
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
        return rows, total

    @staticmethod
    def filter_options(context: AccessContext):
        if not context.can("audit.read"):
            raise PermissionError("audit.read")
        base = AuditService._base_query(context)
        modules = [
            value for (value,) in base.with_entities(AuditEvent.module_id).distinct().order_by(AuditEvent.module_id).all()
            if value
        ]
        actions = [
            value for (value,) in base.with_entities(AuditEvent.action).distinct().order_by(AuditEvent.action).all()
            if value
        ]
        actor_types = [
            value for (value,) in base.with_entities(AuditEvent.actor_type).distinct().order_by(AuditEvent.actor_type).all()
            if value
        ]
        entity_types = [
            value for (value,) in base.with_entities(AuditEvent.entity_type).distinct().order_by(AuditEvent.entity_type).all()
            if value
        ]
        return {
            "modules": modules,
            "actions": actions,
            "actor_types": actor_types,
            "entity_types": entity_types,
        }

    @staticmethod
    def serialise(row: AuditEvent):
        return {
            "id": row.id,
            "created_at": row.created_at.isoformat(),
            "module_id": row.module_id,
            "action": row.action,
            "actor_type": row.actor_type,
            "actor_id": row.actor_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "detail": row.detail or {},
        }

    @staticmethod
    def export_csv(context: AccessContext, **filters) -> str:
        if not context.can("audit.export"):
            raise PermissionError("audit.export")
        query_context = AccessContext(
            identity_type=context.identity_type,
            organisation_id=context.organisation_id,
            user_id=context.user_id,
            api_key_id=context.api_key_id,
            full_access=context.full_access,
            permissions=context.permissions | frozenset({"audit.read"}),
        )
        rows, _ = AuditService.search(
            query_context,
            limit=500,
            offset=0,
            **filters,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "created_at",
                "module",
                "action",
                "actor_type",
                "actor_id",
                "entity_type",
                "entity_id",
                "detail",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.created_at.isoformat(),
                    row.module_id,
                    row.action,
                    row.actor_type,
                    row.actor_id or "",
                    row.entity_type or "",
                    row.entity_id or "",
                    str(row.detail or {}),
                ]
            )
        return output.getvalue()
