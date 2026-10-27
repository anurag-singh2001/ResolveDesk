"""Consent history and erasure requests (S5.2).

consent_events: append-only record of every grant/withdrawal (the app role can only INSERT and
SELECT), so withdrawing never overwrites the evidence of what was agreed. data_requests: a
customer's erasure request; the app may change only its outcome columns and never delete one.
Both: tenant_id + RLS, composite FK to customers.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.rls import disable_rls, enable_rls

APP_ROLE = "resolvedesk_app"
TABLES = ["consent_events", "data_requests"]

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
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
        sa.Column("customer_id", sa.UUID(), nullable=False),
    ]


def _grants(sql: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; {sql}; END $$"
    )


def upgrade() -> None:
    fk = sa.ForeignKeyConstraint(
        ["tenant_id", "customer_id"],
        ["customers.tenant_id", "customers.id"],
        ondelete="RESTRICT",  # evidence must not vanish with a customer row
    )
    op.add_column("users", sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "consent_events",
        *_base(),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("notice_version", sa.String(length=16), nullable=False),
        fk,
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "data_requests",
        *_base(),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=True),
        sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('erasure')", name="ck_data_requests_kind"),
        sa.CheckConstraint(
            "status IN ('pending_approval', 'deferred', 'completed')",
            name="ck_data_requests_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for table in TABLES:
        op.create_index(op.f(f"ix_{table}_tenant_id"), table, ["tenant_id"], unique=False)
        op.create_index(op.f(f"ix_{table}_customer_id"), table, ["customer_id"], unique=False)
        enable_rls(table)
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    op.create_index(
        "uq_data_requests_active",
        "data_requests",
        ["tenant_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending_approval', 'deferred')"),
    )
    # Evidence is never edited (defence in depth on top of the privileges below).
    op.execute(
        "CREATE TRIGGER trg_consent_events_immutable BEFORE UPDATE ON consent_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_update()"
    )
    _grants(
        f"REVOKE UPDATE, DELETE, TRUNCATE ON consent_events FROM {APP_ROLE}; "
        f"REVOKE DELETE, TRUNCATE ON data_requests FROM {APP_ROLE}; "
        f"REVOKE UPDATE ON data_requests FROM {APP_ROLE}; "
        f"GRANT UPDATE (status, reason_code, deferred_until, decided_by, completed_at) "
        f"ON data_requests TO {APP_ROLE}"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        disable_rls(table)
        op.drop_table(table)
    op.drop_column("users", "erased_at")
