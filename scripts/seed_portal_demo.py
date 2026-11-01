"""Hand-run, dev only: write clearly labelled DEMO rows so the platform portal pages are not empty.

    APP_ENV=dev uv run python -m scripts.seed_portal_demo

Writes, for every tenant in the database (no tenant is named here): job runs (job `demo_sweep`,
one ok and one failed), LLM usage (provider `demo`, model `demo-model`), plus one error count
and one open alert (service/rule `demo`). Nothing else is touched: no customers, orders, cases,
proposals or money. Labels all start with `demo` so the rows are easy to spot and delete.

Idempotent: tenant rows have fixed ids (uuid5 of tenant and label) and are skipped when present;
the error count is set (not added to) and the alert is refreshed, so running twice changes nothing.
Uses the owner connection (MIGRATION_DATABASE_URL) because the app role has no grant on the
error and alert tables. Refuses to run unless APP_ENV=dev (an unset APP_ENV counts as prod).
"""

import sys
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_settings

_NS = uuid.UUID("5d0a1c10-0000-4000-8000-00000000d3e0")
DEMO_JOB = "demo_sweep"
DEMO_RULE = "demo_job_failed"


def refusal(app_env: str, owner_url: str | None) -> str | None:
    """Why the script must not run, or None."""
    if app_env != "dev":
        return f"refused: APP_ENV={app_env} (demo rows are written in dev only)"
    if not owner_url:
        return "MIGRATION_DATABASE_URL is not set"
    return None


def _id(tenant_id: uuid.UUID, label: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{tenant_id}/{label}")


def tenant_rows(tenant_id: uuid.UUID, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """The demo job runs and LLM usage for one tenant. Pure: no database."""
    start = now - timedelta(hours=1)
    jobs = [
        {
            "id": _id(tenant_id, f"job-{status}"),
            "tenant_id": tenant_id,
            "job": DEMO_JOB,
            "status": status,
            "started_at": start,
            "finished_at": start + timedelta(seconds=2 if status == "ok" else 1),
            "error_class": "DemoError" if status == "failed" else None,
        }
        for status in ("ok", "failed")
    ]
    usage = [
        {
            "id": _id(tenant_id, f"llm-{outcome}"),
            "tenant_id": tenant_id,
            "role": "main",
            "provider": "demo",
            "model": "demo-model",
            "calls": 3 if outcome == "ok" else 2,
            "input_tokens": 1200,
            "output_tokens": 300,
            "estimated_cost_micro_paise": 1_500_000 if outcome == "ok" else 0,
            "failures": 0 if outcome == "ok" else 1,
            "latency_ms": 2400,
            "outcome": outcome,
            "error_class": "DemoError" if outcome == "error" else None,
        }
        for outcome in ("ok", "error")
    ]
    return {"jobs": jobs, "usage": usage}


_JOB_SQL = text(
    "INSERT INTO job_runs (id, tenant_id, job, status, started_at, finished_at, counts, "
    "error_class) VALUES (:id, :tenant_id, :job, :status, :started_at, :finished_at, "
    "'{}'::jsonb, :error_class) ON CONFLICT (id) DO NOTHING"
)
_USAGE_SQL = text(
    "INSERT INTO llm_usage (id, tenant_id, role, provider, model, calls, input_tokens, "
    "output_tokens, estimated_cost_micro_paise, failures, latency_ms, outcome, error_class) "
    "VALUES (:id, :tenant_id, :role, :provider, :model, :calls, :input_tokens, :output_tokens, "
    ":estimated_cost_micro_paise, :failures, :latency_ms, :outcome, :error_class) "
    "ON CONFLICT (id) DO NOTHING"
)
_ERROR_SQL = text(
    "INSERT INTO error_logs (service, level, event_code, error_class, day, occurrences, "
    "first_at, last_at) VALUES ('demo', 'ERROR', 'demo.seeded_error', 'DemoError', "
    "CAST(:now AS date), 7, :now, :now) ON CONFLICT (service, level, event_code, error_class, day) "
    "DO UPDATE SET occurrences = 7, last_at = EXCLUDED.last_at"
)
_ALERT_SQL = text(
    "INSERT INTO alerts (rule, scope, status, value, threshold, opened_at, last_seen_at) "
    "VALUES (:rule, 'demo', 'open', 3, 1, :now, :now) "
    "ON CONFLICT (rule, scope) WHERE status = 'open' DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at"
)


def seed(engine: Engine, now: datetime) -> dict[str, int]:
    """Write the demo rows in one transaction; returns what was offered per kind."""
    with engine.begin() as conn:
        tenants = conn.execute(text("SELECT id FROM organizations ORDER BY slug")).scalars().all()
        for tid in tenants:
            rows = tenant_rows(tid, now)
            conn.execute(_JOB_SQL, rows["jobs"])
            conn.execute(_USAGE_SQL, rows["usage"])
        conn.execute(_ERROR_SQL, {"now": now})
        conn.execute(_ALERT_SQL, {"rule": DEMO_RULE, "now": now})
    return {"tenants": len(tenants), "error_counts": 1, "alerts": 1}


def main() -> int:
    from datetime import UTC

    settings = get_settings()
    why = refusal(settings.app_env, settings.migration_database_url)
    if why:
        print(why)
        return 1
    engine = create_engine(settings.migration_database_url)
    counts = seed(engine, datetime.now(UTC))
    print(f"demo rows written (safe to repeat): {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
