"""snapshot: consistent operational snapshot RPC

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute((SQL_DIR / "0004_snapshot.sql").read_text())


def downgrade() -> None:
    op.execute(
        "drop function if exists cornucopia.get_operational_snapshot(uuid)"
    )
