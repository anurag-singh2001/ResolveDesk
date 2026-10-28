"""Case owner (S7.2): who is responsible for a case that needs a person.

Plain columns on an existing tenant-owned table, so RLS and grants already cover them. The
owner FK is composite (tenant_id, owner_user_id) so an owner can never be another tenant's
user; deleting the user clears only owner_user_id (PG15+ column list), never tenant_id.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("owner_user_id", sa.UUID(), nullable=True))
    op.add_column("cases", sa.Column("owner_assigned_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_cases_owner_user",
        "cases",
        "users",
        ["tenant_id", "owner_user_id"],
        ["tenant_id", "id"],
        ondelete="SET NULL (owner_user_id)",
    )
    op.create_index("ix_cases_tenant_owner", "cases", ["tenant_id", "owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_cases_tenant_owner", table_name="cases")
    op.drop_constraint("fk_cases_owner_user", "cases", type_="foreignkey")
    op.drop_column("cases", "owner_assigned_at")
    op.drop_column("cases", "owner_user_id")
