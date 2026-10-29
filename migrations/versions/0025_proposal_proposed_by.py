"""Who proposed (S7.5): staff-made proposals carry the staff user id; engine ones stay NULL.

A plain column, no foreign key: proposals are immutable (an UPDATE trigger), and a SET NULL
foreign key would try to UPDATE the row when a user is erased. The id is not personal data on
its own; the user's name is resolved at read time, and an erased user shows as former staff.
Idempotency of a staff proposal is kept by the case row lock (staff_decisions.propose), not by
a unique index: after a remedy switch (S7.10) the same payload may legitimately be proposed again.

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


def downgrade() -> None:
    op.drop_column("action_proposals", "proposed_by")
