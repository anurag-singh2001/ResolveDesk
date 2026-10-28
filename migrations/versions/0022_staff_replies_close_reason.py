"""Staff replies and close reason (S7.6).

ticket_messages gains what a staff message needs: kind (template | note), the template id, the
sender and an idempotency key (a double submit is one message). cases gains close_reason,
closed_at and closed_by_user_id. Plain columns on existing tenant-owned tables: RLS and grants
already cover them.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = "('resolved', 'no_remedy', 'duplicate', 'unreachable')"


def upgrade() -> None:
    op.add_column("ticket_messages", sa.Column("kind", sa.String(16)))
    op.add_column("ticket_messages", sa.Column("template_id", sa.String(48)))
    op.add_column("ticket_messages", sa.Column("sender_user_id", sa.UUID()))
    op.add_column("ticket_messages", sa.Column("idempotency_key", sa.String(160)))
    op.create_check_constraint(
        "ck_ticket_messages_kind",
        "ticket_messages",
        "kind IS NULL OR kind IN ('template', 'note')",
    )
    op.create_index(
        "uq_ticket_messages_idem",
        "ticket_messages",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.add_column("cases", sa.Column("close_reason", sa.String(16)))
    op.add_column("cases", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("cases", sa.Column("closed_by_user_id", sa.UUID()))
    op.create_check_constraint(
        "ck_cases_close_reason", "cases", f"close_reason IS NULL OR close_reason IN {REASONS}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_cases_close_reason", "cases", type_="check")
    op.drop_column("cases", "closed_by_user_id")
    op.drop_column("cases", "closed_at")
    op.drop_column("cases", "close_reason")
    op.drop_index("uq_ticket_messages_idem", table_name="ticket_messages")
    op.drop_constraint("ck_ticket_messages_kind", "ticket_messages", type_="check")
    op.drop_column("ticket_messages", "idempotency_key")
    op.drop_column("ticket_messages", "sender_user_id")
    op.drop_column("ticket_messages", "template_id")
    op.drop_column("ticket_messages", "kind")
