"""resource_writes: audited write_resource RPC; table writes only via RPCs

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute((SQL_DIR / "0003_resource_writes.sql").read_text())


def downgrade() -> None:
    op.execute(
        "drop function if exists cornucopia.write_resource(uuid, text, text, text, uuid, jsonb)"
    )
