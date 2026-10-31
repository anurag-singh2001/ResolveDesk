"""Erasure completion message (S8.8, owner decision P4).

The customer is told once, after the erasure executor succeeds. Their contact is wiped by the
erasure itself, so the destination is copied at request time into a short-lived outbox row
(`erasure_notices`): one row per request, purpose-limited, deleted when the send outcome is
final or after `expires_at` (7 days from the request), whichever comes first. The app role may
INSERT, SELECT, UPDATE and DELETE it (it deletes its own rows); RLS keeps it to its tenant.

`data_requests.completion_message` records the final outcome without any contact detail
(sent | failed | unknown | expired | none); the app role may update just that new column.
`data_requests` also gets a (tenant_id, id) unique key so the outbox can use the composite
foreign key every tenant-owned table uses.

Number 0030 with down_revision 0027 is deliberate: the coordinator renumbers when merging.

Revision ID: 0030
Revises: 0027
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.rls import disable_rls, enable_rls

APP_ROLE = "resolvedesk_app"

revision: str = "0030"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _grants(sql: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; {sql}; END $$"
    )


def upgrade() -> None:
    op.create_unique_constraint("uq_data_requests_tenant_id", "data_requests", ["tenant_id", "id"])
    op.add_column(
        "data_requests", sa.Column("completion_message", sa.String(length=16), nullable=True)
    )
    op.create_check_constraint(
        "ck_data_requests_completion_message",
        "data_requests",
        "completion_message IS NULL OR completion_message IN "
        "('sent', 'failed', 'unknown', 'expired', 'none')",
    )
    op.create_table(
        "erasure_notices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("destination", sa.String(length=320), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("state", sa.String(length=8), server_default="queued", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["data_requests.tenant_id", "data_requests.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "request_id", name="uq_erasure_notices_request"),
        sa.CheckConstraint("channel IN ('phone', 'email')", name="ck_erasure_notices_channel"),
        sa.CheckConstraint("state IN ('queued', 'sending')", name="ck_erasure_notices_state"),
    )
    op.create_index("ix_erasure_notices_tenant_id", "erasure_notices", ["tenant_id"])
    op.create_index("ix_erasure_notices_expires_at", "erasure_notices", ["expires_at"])
    enable_rls("erasure_notices")
    op.execute(
        "CREATE TRIGGER trg_erasure_notices_updated_at BEFORE UPDATE ON erasure_notices "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    _grants(
        f"GRANT UPDATE (completion_message) ON data_requests TO {APP_ROLE}; "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON erasure_notices TO {APP_ROLE}; "
        f"REVOKE TRUNCATE ON erasure_notices FROM {APP_ROLE}"
    )


def downgrade() -> None:
    disable_rls("erasure_notices")
    op.drop_index("ix_erasure_notices_expires_at", table_name="erasure_notices")
    op.drop_index("ix_erasure_notices_tenant_id", table_name="erasure_notices")
    op.drop_table("erasure_notices")
    op.drop_constraint("ck_data_requests_completion_message", "data_requests", type_="check")
    op.drop_column("data_requests", "completion_message")
    op.drop_constraint("uq_data_requests_tenant_id", "data_requests", type_="unique")
