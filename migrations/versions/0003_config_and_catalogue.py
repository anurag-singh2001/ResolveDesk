"""Vertical packs, tenant settings, feature flags, catalogue; pin set_updated_at search_path.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.rls import disable_rls, enable_rls

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ["tenant_settings", "feature_flags", "catalogue_items"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _tenant_base() -> list[sa.Column]:
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        *_timestamps(),
    ]


def upgrade() -> None:
    # Safety-review follow-up: a trigger function must not resolve names via the caller's path.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END $$
        """
    )

    op.create_table(
        "vertical_packs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("definition", JSONB, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "tenant_settings",
        *_tenant_base(),
        sa.Column("brand_id", UUID(as_uuid=True)),
        sa.Column("location_id", UUID(as_uuid=True)),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.CheckConstraint(
            "brand_id IS NULL OR location_id IS NULL", name="ck_tenant_settings_one_scope"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "brand_id",
            "location_id",
            "key",
            name="uq_tenant_settings_scope_key",
            postgresql_nulls_not_distinct=True,
        ),
        sa.ForeignKeyConstraint(["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]
        ),
    )
    op.create_table(
        "feature_flags",
        *_tenant_base(),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.UniqueConstraint("tenant_id", "key", name="uq_feature_flags_key"),
    )
    op.create_table(
        "catalogue_items",
        *_tenant_base(),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("price_paise", sa.BigInteger, nullable=False),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_catalogue_items_sku"),
        sa.ForeignKeyConstraint(["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"]),
        sa.CheckConstraint("price_paise >= 0", name="ck_catalogue_items_price"),
    )
    for table in TENANT_TABLES:
        enable_rls(table)
    for table in ["vertical_packs", *TENANT_TABLES]:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        disable_rls(table)
        op.drop_table(table)
    op.drop_table("vertical_packs")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END $$
        """
    )
