"""App role gets read-only access to vertical_packs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23

vertical_packs is platform-wide (no RLS); a bug on one tenant's request path must not be able
to rewrite pack defaults for every tenant. Packs are written by the owner (seed/migrations).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "resolvedesk_app"


def _if_role_exists(sql: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') "
        f"THEN {sql}; END IF; END $$"
    )


def upgrade() -> None:
    _if_role_exists(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON vertical_packs FROM {APP_ROLE}")
    _if_role_exists(f"GRANT SELECT ON vertical_packs TO {APP_ROLE}")


def downgrade() -> None:
    _if_role_exists(f"GRANT INSERT, UPDATE, DELETE ON vertical_packs TO {APP_ROLE}")
