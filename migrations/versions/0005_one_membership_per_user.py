"""One membership per user per tenant, so a user's role is never ambiguous.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_memberships_tenant_user", "memberships", ["tenant_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_memberships_tenant_user", "memberships", type_="unique")
