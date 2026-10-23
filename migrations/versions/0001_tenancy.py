"""Tenancy tables with row-level security.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from migrations.rls import disable_rls, enable_rls

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["organizations", "brands", "locations", "location_brands", "users", "memberships"]


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "organizations",
        *_base_columns(),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("vertical_pack", sa.String(64), nullable=False),
        sa.CheckConstraint("tenant_id = id", name="ck_organizations_tenant_is_self"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    for table in ("brands", "locations"):
        op.create_table(
            table,
            *_base_columns(),
            sa.Column("slug", sa.String(64), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.UniqueConstraint("tenant_id", "slug", name=f"uq_{table}_tenant_slug"),
            sa.UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id"),
        )
    op.create_table(
        "location_brands",
        *_base_columns(),
        sa.Column("location_id", UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "location_id", "brand_id", name="uq_location_brands"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "users",
        *_base_columns(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
    )
    op.create_table(
        "memberships",
        *_base_columns(),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("brand_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("location_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "role IN ('customer', 'location_manager', 'franchisee_owner', 'hq_owner')",
            name="ck_memberships_role",
        ),
    )
    for table in TABLES:
        enable_rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        disable_rls(table)
        op.drop_table(table)
