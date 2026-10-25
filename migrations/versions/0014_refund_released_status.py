"""Refund ledger status `released`: an operator freed a quarantined reservation (E4.4).

Distinct from `failed` (the provider declined): here the provider never reported anything
and, after its request lifetime, can no longer apply the request (hard rule 7).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "('reserved', 'submitted', 'succeeded', 'failed', 'unknown', 'pending_reconciliation')"
NEW = (
    "('reserved', 'submitted', 'succeeded', 'failed', 'unknown', 'pending_reconciliation', "
    "'released')"
)


def upgrade() -> None:
    op.drop_constraint("ck_refund_operations_status", "refund_operations", type_="check")
    op.create_check_constraint(
        "ck_refund_operations_status", "refund_operations", f"status IN {NEW}"
    )


def downgrade() -> None:
    # A released row can't fit the old set: record it as failed (money is free either way).
    op.execute("UPDATE refund_operations SET status = 'failed' WHERE status = 'released'")
    op.drop_constraint("ck_refund_operations_status", "refund_operations", type_="check")
    op.create_check_constraint(
        "ck_refund_operations_status", "refund_operations", f"status IN {OLD}"
    )
