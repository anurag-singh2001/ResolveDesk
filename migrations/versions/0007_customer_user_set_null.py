"""Removing a login user unlinks their customer record instead of blocking the load.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23

`SET NULL (user_id)` (PostgreSQL 15+) clears only user_id; tenant_id is part of the composite
key and must stay.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "customers_tenant_id_user_id_fkey"


def upgrade() -> None:
    op.drop_constraint(FK, "customers", type_="foreignkey")
    op.execute(
        f"ALTER TABLE customers ADD CONSTRAINT {FK} FOREIGN KEY (tenant_id, user_id) "
        "REFERENCES users (tenant_id, id) ON DELETE SET NULL (user_id)"
    )


def downgrade() -> None:
    op.drop_constraint(FK, "customers", type_="foreignkey")
    op.execute(
        f"ALTER TABLE customers ADD CONSTRAINT {FK} FOREIGN KEY (tenant_id, user_id) "
        "REFERENCES users (tenant_id, id)"
    )
