"""Proposal supersessions (S7.10): an approver switches a pending proposal to another remedy.

Proposals are immutable (their payload hash is what an approval binds to), so "superseded" is
not a status on the proposal: it is a separate append-only row that links the old proposal to
the new one. At most one supersession per old proposal and per new proposal (a chain, never a
fork). The app role can only INSERT and SELECT, and RLS keeps it to its tenant.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.rls import disable_rls, enable_rls

APP_ROLE = "resolvedesk_app"

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proposal_supersessions",
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
        sa.Column("old_proposal_id", sa.UUID(), nullable=False),
        sa.Column("new_proposal_id", sa.UUID(), nullable=False),
        sa.Column("switched_by", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "old_proposal_id"],
            ["action_proposals.tenant_id", "action_proposals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "new_proposal_id"],
            ["action_proposals.tenant_id", "action_proposals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "switched_by"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("old_proposal_id <> new_proposal_id", name="ck_supersession_distinct"),
        sa.UniqueConstraint("tenant_id", "old_proposal_id", name="uq_supersession_old"),
        sa.UniqueConstraint("tenant_id", "new_proposal_id", name="uq_supersession_new"),
    )
    op.create_index("ix_proposal_supersessions_tenant_id", "proposal_supersessions", ["tenant_id"])
    enable_rls("proposal_supersessions")
    op.execute(
        "CREATE TRIGGER trg_proposal_supersessions_immutable BEFORE UPDATE ON "
        "proposal_supersessions FOR EACH ROW EXECUTE FUNCTION reject_update()"
    )
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; REVOKE UPDATE, DELETE, TRUNCATE ON proposal_supersessions FROM {APP_ROLE}; "
        f"END $$"
    )


def downgrade() -> None:
    disable_rls("proposal_supersessions")
    op.drop_index("ix_proposal_supersessions_tenant_id", table_name="proposal_supersessions")
    op.drop_table("proposal_supersessions")
