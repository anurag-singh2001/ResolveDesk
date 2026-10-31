"""Rule-based alerts (S9.4). Evaluated by the scheduler (job `alerts`) or on request.

Each rule returns the conditions that hold right now, as {(rule, scope): (value, threshold)}.
`reconcile` then makes the `alerts` table match: a condition with no open row opens one; one
with an open row only has its last_seen/value refreshed (never a duplicate: a partial unique
index backs this); an open row whose condition no longer holds is resolved with a timestamp.

A rule that could not be read (database error) is NOT treated as clear: its open alerts are
left as they are, because "unknown" is not "fine". Reads are aggregate counts through the
tenant's own RLS session; scope is a tenant slug and a job label, values are integers, and no
message, id or person is read or stored. Nothing is sent anywhere: the portal shows alerts.

Rates are integer basis points; ratios integer percents (no floats).
"""

import logging
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.db import tenant_session
from app.core.models import Case, JobRun, LlmUsage, Organization

log = logging.getLogger(__name__)

Conditions = dict[tuple[str, str], tuple[int, int]]
RULES = ("job_failed", "provider_failure_rate", "escalation_spike", "eval_regression", "stuck_job")
_SCOPE_MAX = 120


def _scope(*parts: str) -> str:
    return ":".join(parts)[:_SCOPE_MAX]


# --- per-tenant rules (read under the tenant's RLS) ------------------------------------------


def _tenant_slug(session: Session) -> str:
    return session.execute(select(Organization.slug)).scalar_one()


def _job_failed(session, slug: str, now: datetime, s: Settings) -> Conditions:
    since = now - timedelta(hours=s.alert_job_lookback_hours)
    rows = session.execute(
        select(JobRun.job, JobRun.status, JobRun.started_at)
        .where(JobRun.status.in_(("ok", "failed")), JobRun.started_at >= since)
        .order_by(JobRun.job, JobRun.started_at.desc())
    ).all()
    latest: dict[str, str] = {}
    for job, status, _ in rows:  # newest first: the first row per job is its latest verdict
        latest.setdefault(job, status)
    return {
        ("job_failed", _scope(slug, job)): (1, 0)
        for job, status in latest.items()
        if status == "failed"
    }


def _stuck_job(session, slug: str, now: datetime, s: Settings) -> Conditions:
    cutoff = now - timedelta(minutes=s.alert_stuck_minutes)
    rows = session.execute(
        select(JobRun.job, func.count())
        .where(JobRun.status == "running", JobRun.started_at < cutoff)
        .group_by(JobRun.job)
    ).all()
    return {("stuck_job", _scope(slug, job)): (n, s.alert_stuck_minutes) for job, n in rows}


def _provider_failure_rate(session, slug: str, now: datetime, s: Settings) -> Conditions:
    since = now - timedelta(hours=s.alert_window_hours)
    calls, failures = session.execute(
        select(
            func.coalesce(func.sum(LlmUsage.calls), 0),
            func.coalesce(func.sum(LlmUsage.failures), 0),
        ).where(LlmUsage.created_at >= since)
    ).one()
    calls, failures = int(calls), int(failures)
    # failures/calls > bps/10000, in integers; too few calls is no verdict.
    if (
        calls >= s.alert_provider_min_calls
        and failures * 10_000 > s.alert_provider_failure_bps * calls
    ):
        return {
            ("provider_failure_rate", slug): (
                failures * 10_000 // calls,
                s.alert_provider_failure_bps,
            )
        }
    return {}


def _escalation_spike(session, slug: str, now: datetime, s: Settings) -> Conditions:
    """Escalated cases opened in the last 24h against the mean of the 7 days before that."""
    day = timedelta(days=1)

    def count(lo: datetime, hi: datetime) -> int:
        return int(
            session.execute(
                select(func.count()).where(
                    Case.status == "escalated", Case.opened_at >= lo, Case.opened_at < hi
                )
            ).scalar_one()
        )

    current = count(now - day, now + timedelta(seconds=1))
    prior7 = count(now - 8 * day, now - day)
    # current > ratio% of (prior7 / 7), in integers; a quiet history still needs a minimum count.
    if (
        current >= s.alert_escalation_min_count
        and current * 7 * 100 > s.alert_escalation_ratio_pct * prior7
    ):
        return {("escalation_spike", slug): (current, s.alert_escalation_min_count)}
    return {}


TENANT_RULES: dict[str, Callable[..., Conditions]] = {
    "job_failed": _job_failed,
    "stuck_job": _stuck_job,
    "provider_failure_rate": _provider_failure_rate,
    "escalation_spike": _escalation_spike,
}


# --- platform-level rules ----------------------------------------------------------------


def _platform_jobs(engine: Engine, now: datetime, s: Settings) -> dict[str, Conditions]:
    since = now - timedelta(hours=s.alert_job_lookback_hours)
    cutoff = now - timedelta(minutes=s.alert_stuck_minutes)
    with engine.connect() as conn:
        done = conn.execute(
            text(
                "SELECT job, status FROM platform_job_runs "
                "WHERE status IN ('ok', 'failed') AND started_at >= :since "
                "ORDER BY job, started_at DESC"
            ),
            {"since": since},
        ).all()
        stuck = conn.execute(
            text(
                "SELECT job, count(*) FROM platform_job_runs "
                "WHERE status = 'running' AND started_at < :cutoff GROUP BY job"
            ),
            {"cutoff": cutoff},
        ).all()
    latest: dict[str, str] = {}
    for job, status in done:
        latest.setdefault(job, status)
    return {
        "job_failed": {
            ("job_failed", _scope("platform", j)): (1, 0)
            for j, st in latest.items()
            if st == "failed"
        },
        "stuck_job": {
            ("stuck_job", _scope("platform", j)): (int(n), s.alert_stuck_minutes) for j, n in stuck
        },
    }


_ROW = re.compile(
    r"^\|\s*(?P<tenant>[^|]+?)\s*\|\s*(?P<pipe>[^|]+?)\s*\|\s*\d+\s*\|\s*(?P<pass>\d+)%"
)


def parse_eval_report(path: Path) -> dict[str, int]:
    """{ 'tenant/pipeline': pass percent } from an eval report table (header row: no match)."""
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m:
            out[f"{m['tenant']}/{m['pipe']}"] = int(m["pass"])
    return out


def _eval_regression(reports_dir: Path, s: Settings) -> Conditions:
    """Latest report against the one before it: a pass-rate drop of at least the threshold."""
    if not reports_dir.is_dir():
        return {}
    files = sorted(reports_dir.glob("eval-*.md"))
    if len(files) < 2:
        return {}
    previous, latest = parse_eval_report(files[-2]), parse_eval_report(files[-1])
    out: Conditions = {}
    for key, now_pass in latest.items():
        drop = previous.get(key, now_pass) - now_pass
        if drop >= s.alert_eval_drop_points:
            out[("eval_regression", _scope(key))] = (drop, s.alert_eval_drop_points)
    return out


# --- reconcile ---------------------------------------------------------------------------


def reconcile(
    engine: Engine, conditions: Conditions, evaluated: set[str], now: datetime
) -> dict[str, int]:
    """Open / refresh / resolve in one short transaction. Only rules in `evaluated` may resolve."""
    opened = refreshed = resolved = 0
    with Session(engine) as session, session.begin():
        rows = session.execute(
            text("SELECT id, rule, scope FROM alerts WHERE status = 'open' FOR UPDATE")
        ).all()
        open_by_key = {(r.rule, r.scope): r.id for r in rows}
        for (rule, scope), (value, threshold) in conditions.items():
            params = {"rule": rule, "scope": scope, "v": value, "t": threshold, "now": now}
            if (rule, scope) in open_by_key:
                session.execute(
                    text(
                        "UPDATE alerts SET value = :v, threshold = :t, last_seen_at = :now "
                        "WHERE rule = :rule AND scope = :scope AND status = 'open'"
                    ),
                    params,
                )
                refreshed += 1
            else:
                session.execute(
                    text(
                        "INSERT INTO alerts (rule, scope, status, value, threshold, opened_at, "
                        "last_seen_at) VALUES (:rule, :scope, 'open', :v, :t, :now, :now) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    params,
                )
                opened += 1
        for (rule, scope), alert_id in open_by_key.items():
            if rule in evaluated and (rule, scope) not in conditions:
                session.execute(
                    text(
                        "UPDATE alerts SET status = 'resolved', resolved_at = :now, "
                        "last_seen_at = :now WHERE id = :id AND status = 'open'"
                    ),
                    {"id": alert_id, "now": now},
                )
                resolved += 1
    return {"opened": opened, "refreshed": refreshed, "resolved": resolved}


def evaluate_alerts(
    engine: Engine,
    tenant_ids: list[uuid.UUID],
    settings: Settings,
    now: datetime | None = None,
    reports_dir: Path | None = None,
) -> dict[str, int]:
    """Run every rule and reconcile. A rule that fails to read is skipped, not cleared."""
    now = now or datetime.now(UTC)
    conditions: Conditions = {}
    failed: set[str] = set()

    for rule, fn in TENANT_RULES.items():
        try:
            for tid in tenant_ids:
                with tenant_session(tid, engine) as session:
                    conditions.update(fn(session, _tenant_slug(session), now, settings))
        except Exception as exc:
            failed.add(rule)
            log.warning("alert rule %s could not be read: %s", rule, type(exc).__name__)
    try:
        for rule, found in _platform_jobs(engine, now, settings).items():
            if rule in failed:
                continue  # its tenant part is unknown, so the rule as a whole is unknown
            conditions.update(found)
    except Exception as exc:
        failed.update({"job_failed", "stuck_job"})
        log.warning("alert rule platform jobs could not be read: %s", type(exc).__name__)
    try:
        conditions.update(
            _eval_regression(reports_dir or Path(settings.alert_eval_reports_dir), settings)
        )
    except Exception as exc:
        failed.add("eval_regression")
        log.warning("alert rule eval_regression could not be read: %s", type(exc).__name__)

    # A rule that failed keeps its open alerts as they are, but must not add stale ones either.
    conditions = {k: v for k, v in conditions.items() if k[0] not in failed}
    return reconcile(engine, conditions, set(RULES) - failed, now)
