from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_engine():
    return current_app.extensions["migrate"].db.engine


def get_metadata():
    db = current_app.extensions["migrate"].db
    if hasattr(db, "metadatas"):
        return db.metadatas[None]
    return db.metadata


config.set_main_option(
    "sqlalchemy.url",
    str(get_engine().url).replace("%", "%%"),
)

target_metadata = get_metadata()


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = get_engine()

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
