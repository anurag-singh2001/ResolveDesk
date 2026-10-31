"""LLM usage and job runs (S9.2).

`llm_usage`: one row per agent run, role, provider and model, from the run's RunBudget.
Numbers and labels only (no prompt or reply text). Cost is an ESTIMATE in integer micro-paise.
`job_runs`: one row per background job execution per tenant (sweep, retention, growth nightly).
Both tables are tenant-owned with the standard RLS policy. tenant_id is NOT NULL: every job
and every agent run is already executed for one tenant (the sweeper, retention and the
nightly all loop per tenant); platform-level jobs (pack refresh) arrive with S9.3.
The app role may INSERT and SELECT; llm_usage is append-only for it, job_runs may only have
its finish columns updated. Follows 0028 (S9.1).

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import disable_rls, enable_rls

APP_ROLE = "resolvedesk_app"

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    now = sa.text("now()")
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        *_base_columns(),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("estimated_cost_micro_paise", sa.BigInteger(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("error_class", sa.String(80), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "outcome IN ('ok', 'error', 'fallback_used')", name="ck_llm_usage_outcome"
        ),
        sa.CheckConstraint(
            "calls >= 0 AND input_tokens >= 0 AND output_tokens >= 0 AND failures >= 0 "
            "AND latency_ms >= 0 AND estimated_cost_micro_paise >= 0",
            name="ck_llm_usage_counters",
        ),
    )
    op.create_index("ix_llm_usage_tenant_id", "llm_usage", ["tenant_id"])
    op.create_index("ix_llm_usage_tenant_created", "llm_usage", ["tenant_id", "created_at"])
    op.create_index("ix_llm_usage_tenant_run", "llm_usage", ["tenant_id", "run_id"])

    op.create_table(
        "job_runs",
        *_base_columns(),
        sa.Column("job", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "counts", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("error_class", sa.String(80), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('running', 'ok', 'failed', 'skipped')", name="ck_job_runs_status"
        ),
    )
    op.create_index("ix_job_runs_tenant_id", "job_runs", ["tenant_id"])
    op.create_index(
        "ix_job_runs_tenant_job_started", "job_runs", ["tenant_id", "job", "started_at"]
    )

    for table in ("llm_usage", "job_runs"):
        enable_rls(table)
        # Every table with updated_at carries set_updated_at (invariant checked in tests).
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; "
        f"REVOKE UPDATE, DELETE, TRUNCATE ON llm_usage FROM {APP_ROLE}; "
        f"REVOKE UPDATE, DELETE, TRUNCATE ON job_runs FROM {APP_ROLE}; "
        f"GRANT UPDATE (status, finished_at, counts, error_class) ON job_runs TO {APP_ROLE}; "
        f"END $$"
    )


def downgrade() -> None:
    for table in ("job_runs", "llm_usage"):
        disable_rls(table)
        op.drop_table(table)
