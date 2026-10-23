"""Maintenance role for dev reseeds and test cleanup: data rights, but RLS still applies.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24

Neon's owner has BYPASSRLS, so owner-run deletes rely only on hand-written tenant filters.
`resolvedesk_maint` (created by scripts/neon_bootstrap.sql, NOBYPASSRLS) may delete what the
app role may not (engine rows, audit rows) but only inside the tenant set for its transaction:
a forgotten WHERE clause fails closed. It never writes platform-wide pack definitions.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAINT = "resolvedesk_maint"


def _require_role(sql: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{MAINT}') THEN "
        f"RAISE EXCEPTION 'role {MAINT} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; {sql}; END $$"
    )


def upgrade() -> None:
    _require_role(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {MAINT}; "
        f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON vertical_packs, alembic_version "
        f"FROM {MAINT}; "
        # Tables created by later migrations (run as this same owner) get the same rights.
        f"EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {MAINT}', current_user)"
    )


def downgrade() -> None:
    _require_role(
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {MAINT}; "
        f"EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {MAINT}', current_user)"
    )
