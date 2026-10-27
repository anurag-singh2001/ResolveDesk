"""Per-case reply language (S7.12: language auto-detection).

Two nullable columns on an existing tenant-owned table, so RLS and grants already cover them.
`language` is NULL until the first message (or the classifier) decides it; `language_pending`
holds a different label seen once, waiting for a second confident message before a switch.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("language", sa.String(10), nullable=True))
    op.add_column("cases", sa.Column("language_pending", sa.String(10), nullable=True))
    for col in ("language", "language_pending"):
        op.create_check_constraint(
            f"ck_cases_{col}",
            "cases",
            f"{col} IS NULL OR {col} IN ('en', 'hi-Latn', 'hi')",
        )


def downgrade() -> None:
    for col in ("language_pending", "language"):
        op.drop_constraint(f"ck_cases_{col}", "cases", type_="check")
        op.drop_column("cases", col)
