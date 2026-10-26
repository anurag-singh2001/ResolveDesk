"""Legal hold on cases (S5.1 retention job skips held cases).

A plain boolean column on an existing tenant-owned table: RLS and grants already cover it.
Nothing in the API sets it (DB/admin only, by design in S5.1).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cases", sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default="false")
    )


def downgrade() -> None:
    op.drop_column("cases", "legal_hold")
