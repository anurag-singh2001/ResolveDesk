"""Explicit `never_sent` flag on executions.

The verifier used to infer "this failed execution never reached the provider" from the error
text prefix. The code paths that know it (executor/voucher refusal, operator release) now
record it, and old rows are backfilled from the same prefixes once, here.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL = """
UPDATE executions SET never_sent = true
WHERE status = 'failed'
  AND (error LIKE 'refused:%' OR error LIKE 'released by operator%')
"""


def upgrade() -> None:
    op.add_column(
        "executions",
        sa.Column("never_sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute(BACKFILL)
    # The app role updates executions by column (0009): the release path sets this one.
    op.execute("GRANT UPDATE (never_sent) ON executions TO resolvedesk_app")


def downgrade() -> None:
    op.drop_column("executions", "never_sent")
