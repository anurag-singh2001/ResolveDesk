"""Platform-level job runs and job leases (S9.3).

`job_leases`: one row per scheduled job name, the committed lease that lets only one app
process run a job at a time (holder, expiry). Not tenant data; app role only.

`platform_job_runs`: one row per platform job execution (pack refresh) and per scheduler-level
skip. It is NOT tenant-owned (no tenant_id, no RLS), like platform_audit_events, so it holds
only a job name, status, integer counts and an exception class name. The app role may INSERT
and SELECT, and update only the finish columns; no DELETE. The platform role reads it only
through `platform_jobs_v` (job, status, day, run count), the S9.1 aggregate-view pattern.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

APP_ROLE = "resolvedesk_app"
PLATFORM_ROLE = "resolvedesk_platform"

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform_job_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            job varchar(40) NOT NULL,
            status varchar(16) NOT NULL
                CONSTRAINT ck_platform_job_runs_status
                CHECK (status IN ('running', 'ok', 'failed', 'skipped')),
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            counts jsonb NOT NULL DEFAULT '{}'::jsonb,
            error_class varchar(80)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_platform_job_runs_job_started ON platform_job_runs (job, started_at)"
    )
    op.execute("REVOKE ALL ON platform_job_runs FROM PUBLIC")
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first';
            END IF;
            REVOKE ALL ON platform_job_runs FROM {APP_ROLE};
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
                REVOKE ALL ON platform_job_runs FROM {PLATFORM_ROLE};
            END IF;
            GRANT SELECT, INSERT ON platform_job_runs TO {APP_ROLE};
            GRANT UPDATE (status, finished_at, counts, error_class)
                ON platform_job_runs TO {APP_ROLE};
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE job_leases (
            job varchar(40) PRIMARY KEY,
            holder uuid NOT NULL,
            expires_at timestamptz NOT NULL
        )
        """
    )
    op.execute("REVOKE ALL ON job_leases FROM PUBLIC")
    op.execute(
        f"""
        DO $$ BEGIN
            REVOKE ALL ON job_leases FROM {APP_ROLE};
            GRANT SELECT, INSERT, UPDATE, DELETE ON job_leases TO {APP_ROLE};
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
                REVOKE ALL ON job_leases FROM {PLATFORM_ROLE};
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE VIEW platform_jobs_v WITH (security_barrier = true, security_invoker = false) AS
        SELECT job::text AS job, status::text AS status,
               (started_at AT TIME ZONE 'UTC')::date AS day, count(*)::bigint AS runs
        FROM public.platform_job_runs
        GROUP BY 1, 2, 3
        """
    )
    op.execute("REVOKE ALL ON platform_jobs_v FROM PUBLIC")
    op.execute(
        f"""
        DO $$ DECLARE r text; BEGIN
            FOREACH r IN ARRAY ARRAY['resolvedesk_app', 'resolvedesk_maint'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON platform_jobs_v FROM %I', r);
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
                GRANT SELECT ON platform_jobs_v TO {PLATFORM_ROLE};
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS platform_jobs_v")
    op.execute("DROP TABLE IF EXISTS platform_job_runs")
    op.execute("DROP TABLE IF EXISTS job_leases")
