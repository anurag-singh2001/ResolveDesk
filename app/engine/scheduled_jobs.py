"""The jobs the in-app scheduler runs (S9.3). Each reuses the code the scripts run, so the
scheduler adds timing and safety, never new behaviour. All are safe to run twice.

- sweep: app.engine.sweeper.sweep_all (job_runs 'sweep', per tenant). Idempotent: every write
  uses the proposal's stable key.
- retention: purge_all, a DRY RUN unless SCHEDULER_RETENTION_APPLY is set (job_runs
  'retention_dry_run' or 'retention_apply'). A dry run writes nothing.
- growth nightly: run_nightly per tenant (job_runs 'growth_nightly'). It only stores signals
  (one per location and period, a second run is a no-op); nothing is sent, so approvals and
  consent are untouched.

Pack refresh is NOT here: it needs the owner credential, so it stays `make refresh`.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine

from app.config import Settings
from app.core.scheduler import ScheduledJob
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine.alerts import evaluate_alerts
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
            "alerts",  # platform-level: reads counts only, writes the alerts table (S9.4)
            settings.scheduler_alerts_interval_seconds,
            lambda: evaluate_alerts(engine, all_tenant_ids(), settings),
        ),
        ScheduledJob(
            "growth_nightly",
            settings.scheduler_growth_interval_seconds,
            lambda: _growth(engine),
            all_tenant_ids,
        ),
    ]
