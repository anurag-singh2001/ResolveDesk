"""Who proposed (S7.5): staff-made proposals carry the staff user id; engine ones stay NULL.

A plain column, no foreign key: proposals are immutable (an UPDATE trigger), and a SET NULL
foreign key would try to UPDATE the row when a user is erased. The id is not personal data on
its own; the user's name is resolved at read time, and an erased user shows as former staff.
The partial unique index makes a staff proposal idempotent: the same case + payload hash can
exist once, however many times the request is repeated or raced.

Revision ID: 0025
Revises: 0023
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("action_proposals", sa.Column("proposed_by", sa.UUID(), nullable=True))
    op.create_index(
        "uq_action_proposals_staff_once",
        "action_proposals",
        ["tenant_id", "case_id", "payload_hash"],
        unique=True,
        postgresql_where=sa.text("proposed_by IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_action_proposals_staff_once", table_name="action_proposals")
    op.drop_column("action_proposals", "proposed_by")
