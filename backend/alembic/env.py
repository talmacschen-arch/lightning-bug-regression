"""Alembic environment script.

SQLite + batch mode (handles ALTER COLUMN via table recreate, design.md §10.1
"SQLite 已知短板和本项目的应对").

DATABASE_URL env var wins over alembic.ini's sqlalchemy.url. Tests use this
to point each fresh-tmpdir run at its own SQLite file.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if db_url is None:
    raise RuntimeError("DATABASE_URL not set and alembic.ini has no sqlalchemy.url")
config.set_main_option("sqlalchemy.url", db_url)

# We write migrations manually (no autogenerate from models in M0; models will
# be added in M1 when sqlite_store CRUD lands). target_metadata stays None.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
