"""A customer can withdraw an erasure request before it runs (S8.5d).

Only widens the status check on data_requests with 'withdrawn'. The active-request unique index
lists the active statuses by name, so a withdrawn request frees the customer to ask again. No
new column (who withdrew and when is in the audit trail); grants are unchanged because
`status` is already updatable by the app role.

Downgrade refuses (raises) while any withdrawn request exists: deleting rows would erase the
customer's evidence that they asked and withdrew, and rewriting them to another status would
state something untrue. Resolve those rows by hand first.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
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
    held = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM data_requests WHERE status = 'withdrawn'"))
        .scalar()
    )
    if held:
        raise RuntimeError(
            f"{held} withdrawn data request(s) exist; refusing to downgrade (see the docstring)"
        )
    op.drop_constraint("ck_data_requests_status", "data_requests", type_="check")
    op.create_check_constraint(
        "ck_data_requests_status",
        "data_requests",
        "status IN ('pending_approval', 'deferred', 'completed')",
    )
