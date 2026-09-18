"""Add tamper-evident audit hash chain.

Revision ID: 0017_audit_integrity
Revises: 0016_vat_return_lifecycle
Create Date: 2026-09-18
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_audit_integrity"
down_revision: Union[str, None] = "0016_vat_return_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHAIN_VERSION = 1
GLOBAL_SCOPE = "__GLOBAL__"


def _normalise_datetime(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return str(value)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def _json_default(value):
    if isinstance(value, datetime):
        return _normalise_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _event_hash(row, *, scope: str, sequence: int, previous_hash: str | None) -> str:
    payload = {
        "action": row["action"],
        "actor_id": row["actor_id"] or "",
        "actor_type": row["actor_type"],
        "chain_scope": scope,
        "chain_sequence": sequence,
        "chain_version": CHAIN_VERSION,
        "created_at": _normalise_datetime(row["created_at"]),
        "detail": row["detail"] or {},
        "entity_id": row["entity_id"] or "",
        "entity_type": row["entity_type"] or "",
        "event_id": row["id"],
        "module_id": row["module_id"],
        "organisation_id": row["organisation_id"] or "",
        "previous_hash": previous_hash or "",
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade():
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.add_column(sa.Column("chain_scope", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("chain_sequence", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("previous_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("event_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("chain_version", sa.Integer(), nullable=True))

    op.create_table(
        "audit_chain_heads",
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("scope_key"),
    )
    op.create_index(
        "ix_audit_chain_heads_organisation_id",
        "audit_chain_heads",
        ["organisation_id"],
        unique=False,
    )

    connection = op.get_bind()
    audit_events = sa.table(
        "audit_events",
        sa.column("id", sa.String(length=36)),
        sa.column("organisation_id", sa.String(length=36)),
        sa.column("actor_type", sa.String(length=40)),
        sa.column("actor_id", sa.String(length=120)),
        sa.column("module_id", sa.String(length=80)),
        sa.column("action", sa.String(length=120)),
        sa.column("entity_type", sa.String(length=80)),
        sa.column("entity_id", sa.String(length=120)),
        sa.column("detail", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("chain_scope", sa.String(length=80)),
        sa.column("chain_sequence", sa.Integer()),
        sa.column("previous_hash", sa.String(length=64)),
        sa.column("event_hash", sa.String(length=64)),
        sa.column("chain_version", sa.Integer()),
    )
    rows = connection.execute(
        sa.select(audit_events).order_by(
            audit_events.c.organisation_id.asc(),
            audit_events.c.created_at.asc(),
            audit_events.c.id.asc(),
        )
    ).mappings().all()

    state: dict[str, dict] = {}
    for row in rows:
        scope = row["organisation_id"] or GLOBAL_SCOPE
        current = state.setdefault(
            scope,
            {
                "organisation_id": row["organisation_id"],
                "last_sequence": 0,
                "last_hash": None,
                "updated_at": row["created_at"],
            },
        )
        sequence = current["last_sequence"] + 1
        digest = _event_hash(
            row,
            scope=scope,
            sequence=sequence,
            previous_hash=current["last_hash"],
        )
        connection.execute(
            audit_events.update()
            .where(audit_events.c.id == row["id"])
            .values(
                chain_scope=scope,
                chain_sequence=sequence,
                previous_hash=current["last_hash"],
                event_hash=digest,
                chain_version=CHAIN_VERSION,
            )
        )
        current["last_sequence"] = sequence
        current["last_hash"] = digest
        current["updated_at"] = row["created_at"]

    organisations = sa.table(
        "organisations",
        sa.column("id", sa.String(length=36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for row in connection.execute(
        sa.select(organisations.c.id, organisations.c.created_at)
    ).mappings():
        state.setdefault(
            row["id"],
            {
                "organisation_id": row["id"],
                "last_sequence": 0,
                "last_hash": None,
                "updated_at": row["created_at"],
            },
        )

    chain_heads = sa.table(
        "audit_chain_heads",
        sa.column("scope_key", sa.String(length=80)),
        sa.column("organisation_id", sa.String(length=36)),
        sa.column("last_sequence", sa.Integer()),
        sa.column("last_hash", sa.String(length=64)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for scope, values in state.items():
        connection.execute(
            chain_heads.insert().values(
                scope_key=scope,
                organisation_id=values["organisation_id"],
                last_sequence=values["last_sequence"],
                last_hash=values["last_hash"],
                updated_at=values["updated_at"] or datetime.now(timezone.utc),
            )
        )

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.alter_column("chain_scope", existing_type=sa.String(length=80), nullable=False)
        batch_op.alter_column("chain_sequence", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("event_hash", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column("chain_version", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint(
            "uq_audit_event_scope_sequence",
            ["chain_scope", "chain_sequence"],
        )
        batch_op.create_index("ix_audit_events_chain_scope", ["chain_scope"], unique=False)
        batch_op.create_index("ix_audit_events_chain_sequence", ["chain_sequence"], unique=False)
        batch_op.create_index("ix_audit_events_event_hash", ["event_hash"], unique=False)


def downgrade():
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_index("ix_audit_events_event_hash")
        batch_op.drop_index("ix_audit_events_chain_sequence")
        batch_op.drop_index("ix_audit_events_chain_scope")
        batch_op.drop_constraint("uq_audit_event_scope_sequence", type_="unique")
        batch_op.drop_column("chain_version")
        batch_op.drop_column("event_hash")
        batch_op.drop_column("previous_hash")
        batch_op.drop_column("chain_sequence")
        batch_op.drop_column("chain_scope")

    op.drop_index("ix_audit_chain_heads_organisation_id", table_name="audit_chain_heads")
    op.drop_table("audit_chain_heads")
