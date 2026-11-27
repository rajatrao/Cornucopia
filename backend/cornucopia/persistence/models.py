"""SQLAlchemy models: the source of truth for generated DDL.

These models describe the schema; the application does not open a SQL
connection with them (the connector is REST only). Alembic renders them to
SQL migrations that the Supabase CLI applies.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, MetaData, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "cornucopia"

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),)


class SystemProbe(Base):
    """Connectivity test records written through the connector."""

    __tablename__ = "system_probes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    note: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        CheckConstraint("source in ('gateway','direct','test','cli')", name="source_known"),
        CheckConstraint("length(note) between 1 and 500", name="note_length"),
    )
