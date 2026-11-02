"""Platform aggregate views over llm_usage and job_runs (S9.5).

Same pattern as 0028: owner-owned views with security_barrier, granted to resolvedesk_platform
only, taken back from the app and maintenance roles. They group by tenant slug, day and a few
labels (provider, model, purpose, outcome, job, status) and return sums and counts only: no
row id, no tenant id, no error class, no text. Read only through GET /platform/ai-usage and
GET /platform/jobs, which write a platform audit entry on every read.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "resolvedesk_platform"
VIEWS = ("platform_llm_usage_v", "platform_job_runs_v")


def upgrade() -> None:
    opts = "WITH (security_barrier = true, security_invoker = false)"
    op.execute(
        f"""
        CREATE VIEW platform_llm_usage_v {opts} AS
        SELECT o.slug::text AS tenant_slug, u.created_at::date AS day,
               u.provider::text AS provider, u.model::text AS model, u.role::text AS purpose,
               u.outcome::text AS outcome,
               count(*)::bigint AS run_count,
               sum(u.calls)::bigint AS call_count,
               sum(u.failures)::bigint AS failure_count,
               sum(u.input_tokens)::bigint AS tokens_in,
               sum(u.output_tokens)::bigint AS tokens_out,
               sum(u.estimated_cost_micro_paise)::bigint AS cost_micro_paise,
               sum(u.latency_ms)::bigint AS latency_ms_total
        FROM public.llm_usage u JOIN public.organizations o ON o.id = u.tenant_id
        GROUP BY o.slug, u.created_at::date, u.provider, u.model, u.role, u.outcome
        """
    )
    op.execute(
        f"""
        CREATE VIEW platform_job_runs_v {opts} AS
        SELECT o.slug::text AS tenant_slug, j.started_at::date AS day, j.job::text AS job,
               j.status::text AS status,
               count(*)::bigint AS run_count,
               (count(*) FILTER (WHERE j.finished_at IS NOT NULL))::bigint AS finished_count,
               coalesce(sum((extract(epoch FROM (j.finished_at - j.started_at)) * 1000)::bigint)
                        FILTER (WHERE j.finished_at IS NOT NULL), 0)::bigint AS duration_ms_total,
               max(j.started_at) AS last_started_at
        FROM public.job_runs j JOIN public.organizations o ON o.id = j.tenant_id
        GROUP BY o.slug, j.started_at::date, j.job, j.status
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
