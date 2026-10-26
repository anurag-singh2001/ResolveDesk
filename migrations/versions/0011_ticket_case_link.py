"""Link a ticket thread to a live case.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("case_id", sa.UUID(), nullable=True))
    op.create_index("ix_tickets_case_id", "tickets", ["case_id"])
    # SET NULL (case_id) only: tenant_id is part of the key and must stay (PG15+).
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT fk_tickets_case FOREIGN KEY (tenant_id, case_id) "
        "REFERENCES cases (tenant_id, id) ON DELETE SET NULL (case_id)"
    )


def downgrade() -> None:
    op.drop_constraint("fk_tickets_case", "tickets", type_="foreignkey")
    op.drop_index("ix_tickets_case_id", table_name="tickets")
    op.drop_column("tickets", "case_id")
