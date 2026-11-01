"""Platform aggregate view over platform_job_runs (S9.3 portal gap).

Same pattern and grants as 0034: an owner-owned view with security_barrier, granted to
resolvedesk_platform only, taken back from the app and maintenance roles. It groups platform-level
(not tenant) job runs by day, job and status and returns counts and sums only: no row id, no
counts payload, no error class, no text. Read only through GET /platform/scheduler-runs, which
writes a platform audit entry on every read. The raw table stays unreachable for the platform role.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "resolvedesk_platform"
VIEWS = ("platform_scheduler_runs_v",)


def upgrade() -> None:
    opts = "WITH (security_barrier = true, security_invoker = false)"
    op.execute(
        f"""
        CREATE VIEW platform_scheduler_runs_v {opts} AS
        SELECT j.started_at::date AS day, j.job::text AS job, j.status::text AS status,
               count(*)::bigint AS run_count,
               (count(*) FILTER (WHERE j.finished_at IS NOT NULL))::bigint AS finished_count,
               coalesce(sum((extract(epoch FROM (j.finished_at - j.started_at)) * 1000)::bigint)
                        FILTER (WHERE j.finished_at IS NOT NULL), 0)::bigint AS duration_ms_total,
               max(j.started_at) AS last_started_at
        FROM public.platform_job_runs j
        GROUP BY j.started_at::date, j.job, j.status
        """
    )
    op.execute(
        f"""
        DO $$ DECLARE r text; v text; BEGIN
            FOREACH r IN ARRAY ARRAY['resolvedesk_app', 'resolvedesk_maint'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    FOREACH v IN ARRAY ARRAY[{", ".join(f"'{v}'" for v in VIEWS)}] LOOP
                        EXECUTE format('REVOKE ALL ON %I FROM %I', v, r);
                    END LOOP;
                END IF;
            END LOOP;
        END $$
        """
    )
    for view in VIEWS:
        op.execute(f"REVOKE ALL ON {view} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON {view} TO {ROLE}")


def downgrade() -> None:
    for view in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")
