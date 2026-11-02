"""S13.2: an owner can reject an erasure request, so `rejected` joins the status list.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_data_requests_status"


def upgrade() -> None:
    op.drop_constraint(NAME, "data_requests", type_="check")
    op.create_check_constraint(
        NAME,
        "data_requests",
        "status IN ('pending_approval', 'deferred', 'completed', 'withdrawn', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint(NAME, "data_requests", type_="check")
    op.create_check_constraint(
        NAME,
        "data_requests",
        "status IN ('pending_approval', 'deferred', 'completed', 'withdrawn')",
    )
