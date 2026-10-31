"""Error log and alerts (S9.4).

`error_logs`: one row per (service, level, event code, exception class, day) with a count.
Codes and counts only: never a message, an id, a tenant or a person, so there is nothing to
scrub. It is NOT tenant-owned (no tenant_id, no RLS), like platform_job_runs. The app role may
INSERT, SELECT and bump the counter columns; no DELETE.

`alerts`: one row per alert condition (rule, scope). A partial unique index allows only one
OPEN row per (rule, scope), so a repeat evaluation cannot duplicate an alert. Scope is a
tenant slug and job label (platform metadata, as in the S9.1 views), the numbers are integers.
Not tenant-owned. The app role (the evaluator) may INSERT, SELECT and update the state columns.

The platform role reads them only through `platform_error_logs_v` and `platform_alerts_v`
(S9.1 pattern: SECURITY DEFINER views, no table grant).

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

APP_ROLE = "resolvedesk_app"
PLATFORM_ROLE = "resolvedesk_platform"

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _grants(table: str, app_grants: str) -> str:
    return f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first';
            END IF;
            REVOKE ALL ON {table} FROM {APP_ROLE};
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
                REVOKE ALL ON {table} FROM {PLATFORM_ROLE};
            END IF;
            {app_grants}
        END $$
        """


def _view_grants(view: str) -> str:
    return f"""
        DO $$ DECLARE r text; BEGIN
            FOREACH r IN ARRAY ARRAY['resolvedesk_app', 'resolvedesk_maint'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON {view} FROM %I', r);
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
                GRANT SELECT ON {view} TO {PLATFORM_ROLE};
            END IF;
        END $$
        """


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE error_logs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            service varchar(40) NOT NULL,
            level varchar(10) NOT NULL
                CONSTRAINT ck_error_logs_level CHECK (level IN ('WARNING', 'ERROR', 'CRITICAL')),
            event_code varchar(80) NOT NULL,
            error_class varchar(80) NOT NULL DEFAULT '',
            day date NOT NULL,
            occurrences bigint NOT NULL CONSTRAINT ck_error_logs_count CHECK (occurrences > 0),
            first_at timestamptz NOT NULL,
            last_at timestamptz NOT NULL,
            CONSTRAINT uq_error_logs_key UNIQUE (service, level, event_code, error_class, day)
        )
        """
    )
    op.execute("REVOKE ALL ON error_logs FROM PUBLIC")
    op.execute(
        _grants(
            "error_logs",
            f"GRANT SELECT, INSERT ON error_logs TO {APP_ROLE}; "
            f"GRANT UPDATE (occurrences, last_at) ON error_logs TO {APP_ROLE};",
        )
    )
    op.execute(
        """
        CREATE TABLE alerts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rule varchar(40) NOT NULL,
            scope varchar(120) NOT NULL DEFAULT '',
            status varchar(10) NOT NULL
                CONSTRAINT ck_alerts_status CHECK (status IN ('open', 'resolved')),
            value bigint NOT NULL,
            threshold bigint NOT NULL,
            opened_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL,
            resolved_at timestamptz,
            CONSTRAINT ck_alerts_resolved
                CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_alerts_one_open ON alerts (rule, scope) WHERE status = 'open'"
    )
    op.execute("CREATE INDEX ix_alerts_opened ON alerts (opened_at)")
    op.execute("REVOKE ALL ON alerts FROM PUBLIC")
    op.execute(
        _grants(
            "alerts",
            f"GRANT SELECT, INSERT ON alerts TO {APP_ROLE}; "
            f"GRANT UPDATE (status, value, threshold, last_seen_at, resolved_at) "
            f"ON alerts TO {APP_ROLE};",
        )
    )
    op.execute(
        """
        CREATE VIEW platform_error_logs_v WITH (security_barrier = true, security_invoker = false)
        AS
        SELECT service::text AS service, level::text AS level, event_code::text AS event_code,
               error_class::text AS error_class, day, occurrences, last_at
        FROM public.error_logs
        """
    )
    op.execute("REVOKE ALL ON platform_error_logs_v FROM PUBLIC")
    op.execute(_view_grants("platform_error_logs_v"))
    op.execute(
        """
        CREATE VIEW platform_alerts_v WITH (security_barrier = true, security_invoker = false) AS
        SELECT rule::text AS rule, scope::text AS scope, status::text AS status, value, threshold,
               opened_at, last_seen_at, resolved_at
        FROM public.alerts
        """
    )
    op.execute("REVOKE ALL ON platform_alerts_v FROM PUBLIC")
    op.execute(_view_grants("platform_alerts_v"))


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS platform_alerts_v")
    op.execute("DROP VIEW IF EXISTS platform_error_logs_v")
    op.execute("DROP TABLE IF EXISTS alerts")
    op.execute("DROP TABLE IF EXISTS error_logs")
