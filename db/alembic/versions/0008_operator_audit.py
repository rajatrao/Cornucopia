"""operator_audit: operators do not bump the operational version

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute((SQL_DIR / "0008_operator_audit.sql").read_text())


def downgrade() -> None:
    pass  # function body reverts with 0002 on a full downgrade

