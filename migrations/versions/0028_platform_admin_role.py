"""Platform-admin database role and aggregate-only views (S9.1).

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-31

`resolvedesk_platform` is the role the platform-admin routes connect as. It is created here
(idempotently, NOLOGIN, NOBYPASSRLS; the owner enables login and sets the password by hand, see
RUNBOOK) and has NO rights on any table. It can only SELECT four aggregate views and EXECUTE one
audit function, all owned by the migration owner. A view reads its base tables with the
owner's rights, which is the SECURITY DEFINER pattern for views; it needs the owner to be able
to read across tenants (true on Neon: the owner has BYPASSRLS; on a plain Postgres owner it
would see nothing, and the isolation test would fail loudly rather than leak).

The views group by tenant slug, day and a status code only. They never select a customer
column, a name, a message or a row id, so they cannot return personal data. Later stories add
their own views (llm_usage, job_runs, logs, alerts) the same way.

`platform_audit_events` is not tenant-owned (no tenant_id, the platform principal has no
tenant). The platform role can write it only through `platform_audit_record()`, a SECURITY
DEFINER function with a pinned search_path that stores actor and route, nothing else.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "resolvedesk_platform"
VIEWS = (
    "platform_tenants_v",
    "platform_case_counts_v",
    "platform_approval_counts_v",
    "platform_activity_v",
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB
                    NOINHERIT;
            END IF;
        END $$
        """
    )
    # Let the migration owner SET ROLE to it (tests exercise the role this way without a
    # password). PG16 creators lose that right by default. Best effort, never fatal.
    op.execute(
        f"""
        DO $$ BEGIN
            EXECUTE 'GRANT {ROLE} TO ' || quote_ident(current_user) || ' WITH SET TRUE';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'could not grant SET on {ROLE} to the owner: %', SQLERRM;
        END $$
        """
    )
    op.execute(
        f"""
        DO $$ BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO {ROLE}', current_database());
        END $$
        """
    )
    # Start from nothing: no table, sequence or other right, whatever default privileges said.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE}")

    op.execute(
        """
        CREATE TABLE platform_audit_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            actor varchar(64) NOT NULL CHECK (actor <> ''),
            route varchar(200) NOT NULL CHECK (route <> '')
        )
        """
    )
    op.execute("REVOKE ALL ON platform_audit_events FROM PUBLIC")
    op.execute(
        """
        CREATE FUNCTION platform_audit_record(p_actor text, p_route text)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            INSERT INTO public.platform_audit_events (actor, route)
            VALUES (left(p_actor, 64), left(p_route, 200))
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform_audit_record(text, text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION platform_audit_record(text, text) TO {ROLE}")

    opts = "WITH (security_barrier = true, security_invoker = false)"
    op.execute(
        f"""
        CREATE VIEW platform_tenants_v {opts} AS
        SELECT o.slug::text AS tenant_slug, o.vertical_pack::text AS vertical_pack
        FROM public.organizations o
        """
    )
    op.execute(
        f"""
        CREATE VIEW platform_case_counts_v {opts} AS
        SELECT o.slug::text AS tenant_slug, c.opened_at::date AS day, c.status::text AS status,
               count(*)::bigint AS case_count
        FROM public.cases c JOIN public.organizations o ON o.id = c.tenant_id
        GROUP BY o.slug, c.opened_at::date, c.status
        """
    )
    op.execute(
        f"""
        CREATE VIEW platform_approval_counts_v {opts} AS
        SELECT o.slug::text AS tenant_slug, a.decided_at::date AS day,
               a.decision::text AS decision, a.mode::text AS mode,
               count(*)::bigint AS approval_count
        FROM public.approvals a JOIN public.organizations o ON o.id = a.tenant_id
        GROUP BY o.slug, a.decided_at::date, a.decision, a.mode
        """
    )
    # No sweeper run log exists yet (job_runs arrives in S9.2): the latest audit entry written
    # by the system actor per tenant is the nearest honest signal, labelled as exactly that.
    op.execute(
        f"""
        CREATE VIEW platform_activity_v {opts} AS
        SELECT o.slug::text AS tenant_slug, max(e.occurred_at) AS last_system_event_at
        FROM public.organizations o
        LEFT JOIN public.audit_events e ON e.tenant_id = o.id AND e.actor_type = 'system'
        GROUP BY o.slug
        """
    )
    # Default privileges hand the app and maintenance roles DML on every new table and view.
    # These objects are the platform's own: take them back from both (cross-tenant totals are
    # for the platform role only).
    op.execute(
        f"""
        DO $$ DECLARE r text; o text; BEGIN
            FOREACH r IN ARRAY ARRAY['resolvedesk_app', 'resolvedesk_maint'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    FOREACH o IN ARRAY ARRAY['platform_audit_events', {", ".join(f"'{v}'" for v in VIEWS)}] LOOP
                        EXECUTE format('REVOKE ALL ON %I FROM %I', o, r);
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
    op.execute("DROP FUNCTION IF EXISTS platform_audit_record(text, text)")
    op.execute("DROP TABLE IF EXISTS platform_audit_events")
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {ROLE}', current_database());
                BEGIN
                    EXECUTE 'REVOKE {ROLE} FROM ' || quote_ident(current_user);
                EXCEPTION WHEN OTHERS THEN
                    RAISE NOTICE 'could not revoke {ROLE} from the owner: %', SQLERRM;
                END;
            END IF;
        END $$
        """
    )
    # The role stays (it may own a password and a connection); it is left with no rights.
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                REVOKE ALL ON SCHEMA public FROM {ROLE};
            END IF;
        END $$
        """
    )
