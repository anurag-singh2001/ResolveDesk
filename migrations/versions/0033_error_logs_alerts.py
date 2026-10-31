"""Error log and alerts (S9.4).

`error_logs`: one row per (service, level, event code, exception class, day) with a count.
Codes and counts only: never a message, an id, a tenant or a person, so there is nothing to
scrub. It is NOT tenant-owned (no tenant_id, no RLS), like platform_job_runs.

`alerts`: one row per alert condition (rule, scope). A partial unique index allows only one
OPEN row per (rule, scope), so a repeat evaluation cannot duplicate an alert. Scope is a
tenant slug and job label (platform metadata, as in the S9.1 views), the numbers are integers.
Not tenant-owned.

The app role has NO grant on either table (alerts.scope names tenants, so tenant request code,
which runs as the app role, must not read it). It writes only through two SECURITY DEFINER
functions (search_path pinned, EXECUTE for the app role only): `log_error_count` (upsert one
counter) and `alerts_apply` (open, refresh and resolve in one call; returns counts).

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


def _no_table_grants(table: str) -> str:
    return f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first';
            END IF;
            REVOKE ALL ON {table} FROM {APP_ROLE};
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PLATFORM_ROLE}') THEN
                REVOKE ALL ON {table} FROM {PLATFORM_ROLE};
            END IF;
        END $$
        """


def _function_grants(signature: str) -> str:
    return f"""
        DO $$ BEGIN
            REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE};
        END $$
        """


LOG_FN = "log_error_count(text, text, text, text, date, bigint, timestamptz)"
ALERTS_FN = "alerts_apply(jsonb, text[], jsonb, timestamptz)"


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
    op.execute(_no_table_grants("error_logs"))
    op.execute(
        """
        CREATE FUNCTION log_error_count(p_service text, p_level text, p_code text, p_cls text,
                                        p_day date, p_n bigint, p_at timestamptz)
        RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            INSERT INTO error_logs (service, level, event_code, error_class, day, occurrences,
                                    first_at, last_at)
            VALUES (left(p_service, 40), p_level, left(p_code, 80), left(p_cls, 80), p_day,
                    greatest(p_n, 1), p_at, p_at)
            ON CONFLICT (service, level, event_code, error_class, day) DO UPDATE
            SET occurrences = error_logs.occurrences + EXCLUDED.occurrences,
                last_at = EXCLUDED.last_at
        $$
        """
    )
    op.execute(_function_grants(LOG_FN))
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
    op.execute(_no_table_grants("alerts"))
    op.execute(
        """
        CREATE FUNCTION alerts_apply(p_conditions jsonb, p_evaluated text[], p_protected jsonb,
                                     p_now timestamptz)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
            c jsonb; n int; opened int := 0; refreshed int := 0; resolved int := 0;
        BEGIN
            FOR c IN SELECT * FROM jsonb_array_elements(p_conditions) LOOP
                UPDATE alerts SET value = (c->>'value')::bigint,
                       threshold = (c->>'threshold')::bigint, last_seen_at = p_now
                WHERE rule = left(c->>'rule', 40) AND scope = left(c->>'scope', 120)
                  AND status = 'open';
                GET DIAGNOSTICS n = ROW_COUNT;
                IF n > 0 THEN
                    refreshed := refreshed + n;
                ELSE
                    INSERT INTO alerts (rule, scope, status, value, threshold, opened_at,
                                        last_seen_at)
                    VALUES (left(c->>'rule', 40), left(c->>'scope', 120), 'open',
                            (c->>'value')::bigint, (c->>'threshold')::bigint, p_now, p_now)
                    ON CONFLICT DO NOTHING;
                    GET DIAGNOSTICS n = ROW_COUNT;
                    opened := opened + n;
                END IF;
            END LOOP;
            -- Resolve what no longer holds, but only where the rule was actually read:
            -- p_evaluated = rules read in full; p_protected = {rule, prefix} whose read failed.
            UPDATE alerts a SET status = 'resolved', resolved_at = p_now, last_seen_at = p_now
            WHERE a.status = 'open'
              AND a.rule = ANY (p_evaluated)
              AND NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(p_conditions) e
                  WHERE e->>'rule' = a.rule AND e->>'scope' = a.scope)
              AND NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(p_protected) pr
                  WHERE pr->>'rule' = a.rule
                    AND (a.scope = pr->>'prefix'
                         OR left(a.scope, length(pr->>'prefix') + 1) IN
                            ((pr->>'prefix') || ':', (pr->>'prefix') || '/')));
            GET DIAGNOSTICS resolved = ROW_COUNT;
            RETURN jsonb_build_object('opened', opened, 'refreshed', refreshed,
                                      'resolved', resolved);
        END $$
        """
    )
    op.execute(_function_grants(ALERTS_FN))
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
    op.execute(f"DROP FUNCTION IF EXISTS {ALERTS_FN}")
    op.execute(f"DROP FUNCTION IF EXISTS {LOG_FN}")
    op.execute("DROP VIEW IF EXISTS platform_alerts_v")
    op.execute("DROP VIEW IF EXISTS platform_error_logs_v")
    op.execute("DROP TABLE IF EXISTS alerts")
    op.execute("DROP TABLE IF EXISTS error_logs")
