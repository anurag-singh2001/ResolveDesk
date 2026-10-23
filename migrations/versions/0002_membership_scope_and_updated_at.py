"""Membership scope as tenant-bound join tables; updated_at maintained by trigger.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from migrations.rls import disable_rls, enable_rls

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, scope column, referenced table)
SCOPE_TABLES = [
    ("membership_brands", "brand_id", "brands"),
    ("membership_locations", "location_id", "locations"),
]
TOUCHED_TABLES = [
    "organizations",
    "brands",
    "locations",
    "location_brands",
    "users",
    "memberships",
    "membership_brands",
    "membership_locations",
]


def upgrade() -> None:
    # Arrays can't carry FKs, so a membership could name another tenant's brand/location.
    op.drop_column("memberships", "brand_ids")
    op.drop_column("memberships", "location_ids")
    op.create_unique_constraint("uq_memberships_tenant_id", "memberships", ["tenant_id", "id"])

    for table, column, target in SCOPE_TABLES:
        op.create_table(
            table,
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("membership_id", UUID(as_uuid=True), nullable=False),
            sa.Column(column, UUID(as_uuid=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "membership_id", column, name=f"uq_{table}"),
            sa.ForeignKeyConstraint(
                ["tenant_id", "membership_id"],
                ["memberships.tenant_id", "memberships.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], ondelete="CASCADE"
            ),
        )
        enable_rls(table)

    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END $$
        """
    )
    for table in TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    for table in TOUCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    for table, _, _ in reversed(SCOPE_TABLES):
        disable_rls(table)
        op.drop_table(table)
    op.drop_constraint("uq_memberships_tenant_id", "memberships", type_="unique")
    op.add_column(
        "memberships",
        sa.Column("location_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
    )
    op.add_column(
        "memberships",
        sa.Column("brand_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
    )
