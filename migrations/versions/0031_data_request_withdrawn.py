"""A customer can withdraw an erasure request before it runs (S8.5d).

Only widens the status check on data_requests with 'withdrawn'. The active-request unique index
lists the active statuses by name, so a withdrawn request frees the customer to ask again. No
new column (who withdrew and when is in the audit trail); grants are unchanged because
`status` is already updatable by the app role.

Revision ID: 0031
Revises: 0024
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_data_requests_status", "data_requests", type_="check")
    op.create_check_constraint(
        "ck_data_requests_status",
        "data_requests",
        "status IN ('pending_approval', 'deferred', 'completed', 'withdrawn')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM data_requests WHERE status = 'withdrawn'")
    op.drop_constraint("ck_data_requests_status", "data_requests", type_="check")
    op.create_check_constraint(
        "ck_data_requests_status",
        "data_requests",
        "status IN ('pending_approval', 'deferred', 'completed')",
    )
