"""Customer's remedy choice on a case (S7.9).

One nullable column on an existing tenant-owned table, so RLS and grants already cover it.
It holds only an option code ("voucher", "refund_50pct"); the rule check happens in code.
Follows 0023 (S7.10); 0022 is S7.6.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("remedy_choice", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "remedy_choice")
