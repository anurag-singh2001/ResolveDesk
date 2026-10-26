"""Customer language preference (S5.6: Hindi templates).

A plain column on an existing tenant-owned table, so RLS and grants already cover it. Default
`en`; only the customer's own choice changes it. Constrained to the supported codes.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="en"),
    )
    op.create_check_constraint(
        "customers_preferred_language_check",
        "customers",
        "preferred_language IN ('en', 'hi-Latn', 'hi')",
    )


def downgrade() -> None:
    op.drop_constraint("customers_preferred_language_check", "customers", type_="check")
    op.drop_column("customers", "preferred_language")
