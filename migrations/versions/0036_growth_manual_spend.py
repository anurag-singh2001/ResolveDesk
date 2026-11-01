"""S11.3b: growth_manual_spend, hand-entered ad spend on channels the platform cannot see.

Tenant-owned, RLS on. Append-only for the app role: UPDATE, DELETE and TRUNCATE are taken away,
so an entry is corrected by a new entry, never silently changed. Rows are never verified.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.rls import disable_rls, enable_rls

APP_ROLE = "resolvedesk_app"

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "growth_manual_spend",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("entered_by", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id", "entered_by"], ["users.tenant_id", "users.id"]),
        sa.CheckConstraint("amount_paise > 0", name="ck_growth_manual_spend_amount"),
        sa.CheckConstraint("period_end >= period_start", name="ck_growth_manual_spend_period"),
    )
    op.create_index("ix_growth_manual_spend_tenant_id", "growth_manual_spend", ["tenant_id"])
    enable_rls("growth_manual_spend")
    op.execute(
        "CREATE TRIGGER trg_growth_manual_spend_updated_at BEFORE UPDATE ON growth_manual_spend "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; REVOKE UPDATE, DELETE, TRUNCATE ON growth_manual_spend FROM {APP_ROLE}; END $$"
    )


def downgrade() -> None:
    disable_rls("growth_manual_spend")
    op.drop_table("growth_manual_spend")
