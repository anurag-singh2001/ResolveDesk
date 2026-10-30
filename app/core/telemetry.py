"""Persisted LLM usage and job runs (S9.2).

Everything here is best effort: a recording failure is logged (exception class only) and never
reaches the caller, so a customer-facing run or a background job is unaffected. Each write is
its own short tenant transaction, opened only after the work (and any network call) is done
(hard rule 5). Only numbers, labels and exception class names are stored: never a prompt, a
reply, a message or an exception message (hard rule 7 spirit; they can echo request details).
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine

from app.config import Settings, get_settings
from app.core.db import tenant_session
from app.core.models import JobRun, LlmUsage

log = logging.getLogger(__name__)

MICRO = 1_000_000  # micro-paise per paise: price (paise per million tokens) x tokens


def estimate_cost_micro_paise(
    settings: Settings, provider: str, model: str, input_tokens: int, output_tokens: int
) -> int:
    """An ESTIMATE from the settings price table, in integer micro-paise (no floats).
    paise per million tokens x tokens = micro-paise exactly. Unlisted models cost 0."""
    price_in, price_out = settings.llm_prices_paise_per_million.get(f"{provider}/{model}", (0, 0))
    return input_tokens * price_in + output_tokens * price_out


def _outcome(u: dict[str, Any]) -> str:
    if u["fallback"]:
        return "fallback_used"
    return "error" if u["failures"] and u["failures"] >= u["calls"] else "ok"


def record_llm_usage(
    engine: Engine,
    tenant_id: uuid.UUID,
    budget,
    run_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> None:
    """Write the run's per-model usage rows from its RunBudget. Never raises."""
    try:
        s = settings or get_settings()
        rows = budget.take_usage() if budget is not None else []
        if not rows:
            return
        with tenant_session(tenant_id, engine) as session:
            for u in rows:
                session.add(
                    LlmUsage(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        role=u["role"][:16],
                        provider=u["provider"][:16],
                        model=u["model"][:80],
                        calls=u["calls"],
                        input_tokens=u["input_tokens"],
                        output_tokens=u["output_tokens"],
                        estimated_cost_micro_paise=estimate_cost_micro_paise(
                            s, u["provider"], u["model"], u["input_tokens"], u["output_tokens"]
                        ),
                        failures=u["failures"],
                        latency_ms=u["latency_ms"],
                        outcome=_outcome(u),
                        error_class=(u["error_class"] or None) and u["error_class"][:80],
                    )
                )
    except Exception as exc:
        log.warning("could not record LLM usage: %s", type(exc).__name__)


def _int_counts(counts: dict[str, Any] | None) -> dict[str, int]:
    return {str(k)[:40]: int(v) for k, v in (counts or {}).items() if isinstance(v, int)}


def start_job(engine: Engine, tenant_id: uuid.UUID, job: str) -> uuid.UUID | None:
    """A 'running' row; None when it could not be written."""
    try:
        with tenant_session(tenant_id, engine) as session:
            row = JobRun(
                tenant_id=tenant_id, job=job, status="running", started_at=datetime.now(UTC)
            )
            session.add(row)
            session.flush()
            return row.id
    except Exception as exc:
        log.warning("could not record start of job %s: %s", job, type(exc).__name__)
        return None


def finish_job(
    engine: Engine,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID | None,
    status: str,
    counts: dict[str, Any] | None = None,
    error_class: str | None = None,
) -> None:
    """Close the row (status ok, failed or skipped). Never raises."""
    if job_id is None:
        return
    try:
        with tenant_session(tenant_id, engine) as session:
            row = session.get(JobRun, job_id)
            if row is None:
                return
            row.status = status
            row.finished_at = datetime.now(UTC)
            row.counts = _int_counts(counts)
            row.error_class = error_class[:80] if error_class else None
    except Exception as exc:
        log.warning("could not record end of job: %s", type(exc).__name__)


def run_job[T](
    engine: Engine,
    tenant_id: uuid.UUID,
    job: str,
    fn: Callable[[], T],
    counts_of: Callable[[T], dict[str, Any]] | None = None,
) -> T:
    """Run `fn` (outside any transaction of ours), recording a job_runs row around it. The
    job's own result or exception passes through untouched, whatever the recording does."""
    job_id = start_job(engine, tenant_id, job)
    try:
        result = fn()
    except Exception as exc:
        finish_job(engine, tenant_id, job_id, "failed", error_class=type(exc).__name__)
        raise
    try:
        counts = counts_of(result) if counts_of else {}
    except Exception:
        counts = {}
    finish_job(engine, tenant_id, job_id, "ok", counts)
    return result
