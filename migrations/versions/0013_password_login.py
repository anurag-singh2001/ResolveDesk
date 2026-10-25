"""Password login: users.password_hash, login_failures (lockout), public business directory.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-25

- users.password_hash: bcrypt hash, NULL = no password login for that user.
- users.password_is_demo: the hash is of a known demo password; login refuses it unless demo
  accounts are enabled, so a dev-seeded DB served in prod has no known-password logins.
- login_failures: tenant-owned (RLS) counter rows for the lockout window. The app may insert,
  read and delete them (success clears them; old rows are pruned), never update.
- public_businesses(): the login screen's business picker needs slug/name/vertical of every
  organization before anyone is logged in, which RLS (rightly) never allows the app role.
  A SECURITY DEFINER function owned by the migration owner returns exactly those three
  columns and nothing else; the app role may only EXECUTE it. It relies on the owner having
  BYPASSRLS (true on Neon, see migrations/rls.py); without it the function returns no rows,
  which fails closed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.rls import enable_rls

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "resolvedesk_app"


def _grants(sql: str) -> None:
    """Fail loudly if the app role is missing: a skipped REVOKE would leave rights too wide."""
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; {sql}; END $$"
    )


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("password_is_demo", sa.Boolean(), server_default="false", nullable=False),
    )

    op.create_table(
        "login_failures",
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("email_hash ~ '^[0-9a-f]{64}$'", name="ck_login_failures_hash"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_login_failures_tenant_id"), "login_failures", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_login_failures_key_time",
        "login_failures",
        ["tenant_id", "email_hash", "failed_at"],
        unique=False,
    )
    enable_rls("login_failures")
    op.execute(
        "CREATE TRIGGER trg_login_failures_updated_at BEFORE UPDATE ON login_failures "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE FUNCTION public_businesses()
        RETURNS TABLE (slug text, name text, vertical_pack text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT o.slug::text, o.name::text, o.vertical_pack::text
            FROM public.organizations o
            ORDER BY o.name, o.slug
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public_businesses() FROM PUBLIC")
    _grants(
        f"GRANT EXECUTE ON FUNCTION public_businesses() TO {APP_ROLE}; "
        f"REVOKE UPDATE, TRUNCATE ON login_failures FROM {APP_ROLE}; "
        f"GRANT SELECT, INSERT, DELETE ON login_failures TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public_businesses()")
    op.execute("DROP TRIGGER IF EXISTS trg_login_failures_updated_at ON login_failures")
    op.drop_index("ix_login_failures_key_time", table_name="login_failures")
    op.drop_index(op.f("ix_login_failures_tenant_id"), table_name="login_failures")
    op.drop_table("login_failures")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_is_demo")
    op.drop_column("users", "password_hash")
