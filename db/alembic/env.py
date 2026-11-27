from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, text

from cornucopia.persistence.models import SCHEMA, Base

config = context.config
target_metadata = Base.metadata
url = os.environ.get("CORNUCOPIA_MIGRATION_DB_URL") or config.get_main_option("sqlalchemy.url")

COMMON = dict(
    target_metadata=target_metadata,
    version_table_schema=SCHEMA,
    include_schemas=True,
    include_name=lambda name, type_, parent: type_ != "schema" or name == SCHEMA,
    compare_type=True,
    transaction_per_migration=False,
)


def run_offline() -> None:
    context.configure(url=url, literal_binds=True, transactional_ddl=False, dialect_opts={"paramstyle": "named"}, **COMMON)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(f"create schema if not exists {SCHEMA}"))
        context.configure(connection=conn, **COMMON)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
