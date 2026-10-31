"""The jobs the in-app scheduler runs (S9.3). Each reuses the code the scripts run, so the
scheduler adds timing and safety, never new behaviour.

- sweep: app.engine.sweeper.sweep_all (job_runs 'sweep', per tenant)
- retention: purge_all, a DRY RUN unless SCHEDULER_RETENTION_APPLY is set (job_runs
  'retention_dry_run' or 'retention_apply')
- growth nightly: run_nightly per tenant (job_runs 'growth_nightly'). It only stores signals;
  nothing is sent, so approvals and consent checks are untouched.
- pack refresh: dev only, platform-level (platform_job_runs 'pack_refresh'). Elsewhere it is
  recorded as skipped, because it writes with the owner role.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine

from app.config import Settings
from app.core.scheduler import ScheduledJob
from app.core.telemetry import run_platform_job, start_platform_job
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine.retention import purge_all
from app.engine.sweeper import sweep_all
from app.modules.growth.signals import run_nightly

log = logging.getLogger(__name__)


def all_tenant_ids() -> list[uuid.UUID]:
    return [tenant_id_for(load_tenant(f).slug) for f in tenant_dirs()]


def _growth(engine: Engine) -> None:
    for tid in all_tenant_ids():
        try:
            run_nightly(engine, tid, datetime.now(UTC))
        except Exception as exc:  # recorded by run_job; one tenant never stops the rest
            log.warning("growth nightly failed for a tenant: %s", type(exc).__name__)


def _pack_refresh(engine: Engine, settings: Settings) -> None:
    if settings.app_env != "dev" or not settings.migration_database_url:
        start_platform_job(engine, "pack_refresh", "skipped")
        return

    def refresh() -> list[str]:
        from app.rag.embeddings import FastEmbedder
        from scripts.seed import refresh_packs

        return refresh_packs(
            tenant_dirs(), create_engine(settings.migration_database_url), engine, FastEmbedder()
        )

    run_platform_job(engine, "pack_refresh", refresh, lambda lines: {"tenants": len(lines)})


def build_jobs(settings: Settings, engine: Engine) -> list[ScheduledJob]:
    apply = settings.scheduler_retention_apply
    return [
        ScheduledJob(
            "sweep",
            settings.scheduler_sweep_interval_seconds,
            lambda: sweep_all(engine),
            all_tenant_ids,
        ),
        ScheduledJob(
            "retention_apply" if apply else "retention_dry_run",
            settings.scheduler_retention_interval_seconds,
            lambda: purge_all(engine, apply=apply),
            all_tenant_ids,
        ),
        ScheduledJob(
            "growth_nightly",
            settings.scheduler_growth_interval_seconds,
            lambda: _growth(engine),
            all_tenant_ids,
        ),
        ScheduledJob(
            "pack_refresh",
            settings.scheduler_pack_refresh_interval_seconds,
            lambda: _pack_refresh(engine, settings),
        ),
    ]
