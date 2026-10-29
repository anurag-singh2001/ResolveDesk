"""Send-time frequency cap on campaign members (S8.5b).

`claimed_at` is when the executor claimed a member for sending (set in the same short
transaction as the per-phone advisory lock and the cap check), so the cap is counted from real
sends, not from when the audience was picked. `skipped` is a new terminal status for a member
left unsent because the cap would have been broken; `skip_reason` holds the code. Both columns
are on an existing tenant-owned table, so RLS and grants already cover them.
Follows 0024 (the other numbers are held by other stories).

Revision ID: 0029
Revises: 0024
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "send_status IN ('pending', 'submitted', 'processing', 'succeeded', 'failed', 'unknown')"
NEW = (
    "send_status IN ('pending', 'submitted', 'processing', 'succeeded', 'failed', 'unknown', "
    "'skipped')"
)


def upgrade() -> None:
    op.add_column(
        "campaign_members", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("campaign_members", sa.Column("skip_reason", sa.String(32), nullable=True))
    op.drop_constraint("ck_campaign_members_send_status", "campaign_members", type_="check")
    op.create_check_constraint("ck_campaign_members_send_status", "campaign_members", NEW)
    # The app role has column-level UPDATE here (0015); the executor writes the new columns.
    op.execute("GRANT UPDATE (claimed_at, skip_reason) ON campaign_members TO resolvedesk_app")
    # Backfill: members already sent keep a claim time so the cap sees them.
    op.execute(
        "UPDATE campaign_members SET claimed_at = updated_at "
        "WHERE send_status IN ('submitted', 'processing', 'succeeded', 'unknown')"
    )


def downgrade() -> None:
    op.execute("UPDATE campaign_members SET send_status = 'failed' WHERE send_status = 'skipped'")
    op.drop_constraint("ck_campaign_members_send_status", "campaign_members", type_="check")
    op.create_check_constraint("ck_campaign_members_send_status", "campaign_members", OLD)
    op.drop_column("campaign_members", "skip_reason")
    op.drop_column("campaign_members", "claimed_at")
