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

import json
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
from app.core.models import AuditEvent, JobRun, LlmUsage, Organization

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
    """Cases that escalated (distinct `case.escalated` audit events) in the last 24h against
    the daily mean of the 7 days before: a case that was resolved since still counts."""
    day = timedelta(days=1)

    def count(lo: datetime, hi: datetime) -> int:
        return int(
            session.execute(
                select(func.count(func.distinct(AuditEvent.entity_id))).where(
                    AuditEvent.event == "case.escalated",
                    AuditEvent.occurred_at >= lo,
                    AuditEvent.occurred_at < hi,
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


_META = re.compile(r"^- (set|models): (.*)$")


def _report_meta(path: Path) -> tuple[str, str]:
    """(set, models) lines of a report; two reports compare only when both match."""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _META.match(line)
        if m:
            found[m[1]] = m[2].strip()
    return found.get("set", ""), found.get("models", "")


def _eval_regression(reports_dir: Path, s: Settings) -> Conditions | None:
    """Latest report against the newest earlier one with the same set and models. None = not
    evaluated (no folder, fewer than two reports, no table rows, nothing comparable): the
    caller then resolves nothing, because "could not compare" is not "no regression"."""
    if not reports_dir.is_dir():
        return None
    files = sorted(reports_dir.glob("eval-*.md"))
    if len(files) < 2:
        return None
    latest_file, meta = files[-1], _report_meta(files[-1])
    latest = parse_eval_report(latest_file)
    if not latest:
        return None
    for older in reversed(files[:-1]):
        if _report_meta(older) != meta:
            continue
        previous = parse_eval_report(older)
        if not previous:
            return None
        out: Conditions = {}
        for key, now_pass in latest.items():
            drop = previous.get(key, now_pass) - now_pass
            if drop >= s.alert_eval_drop_points:
                out[("eval_regression", _scope(key))] = (drop, s.alert_eval_drop_points)
        return out
    return None


# --- reconcile ---------------------------------------------------------------------------

_APPLY = text(
    "SELECT alerts_apply(CAST(:c AS jsonb), CAST(:ev AS text[]), CAST(:pr AS jsonb), :now)"
)


def reconcile(
    engine: Engine,
    conditions: Conditions,
    evaluated: set[str],
    now: datetime,
    protected: list[tuple[str, str]] | None = None,
) -> dict[str, int]:
    """Open / refresh / resolve in ONE call to the SECURITY DEFINER function `alerts_apply`
    (the app role has no grant on the table). Resolves only rules in `evaluated`, and never an
    alert whose (rule, scope prefix) is in `protected` (its read failed)."""
    payload = [
        {"rule": r, "scope": sc, "value": v, "threshold": t}
        for (r, sc), (v, t) in conditions.items()
    ]
    with engine.begin() as conn:
        result = conn.execute(
            _APPLY,
            {
                "c": json.dumps(payload),
                "ev": sorted(evaluated),
                "pr": json.dumps([{"rule": r, "prefix": p} for r, p in (protected or [])]),
                "now": now,
            },
        ).scalar_one()
    return {k: int(result[k]) for k in ("opened", "refreshed", "resolved")}


def evaluate_alerts(
    engine: Engine,
    tenant_ids: list[uuid.UUID],
    settings: Settings,
    now: datetime | None = None,
    reports_dir: Path | None = None,
) -> dict[str, int]:
    """Run every rule and reconcile. A read that fails protects only what it would have
    decided: one tenant's failure leaves that tenant's alerts for that rule alone."""
    now = now or datetime.now(UTC)
    conditions: Conditions = {}
    evaluated = set(RULES)
    protected: list[tuple[str, str]] = []

    for tid in tenant_ids:
        slug: str | None = None
        for rule, fn in TENANT_RULES.items():
            try:
                with tenant_session(tid, engine) as session:
                    slug = _tenant_slug(session)
                    conditions.update(fn(session, slug, now, settings))
            except Exception as exc:
                log.warning("alert rule %s could not be read: %s", rule, type(exc).__name__)
                if slug is None:  # cannot tell which scopes are this tenant's: protect the rule
                    evaluated.discard(rule)
                else:
                    protected.append((rule, slug))
    try:
        for found in _platform_jobs(engine, now, settings).values():
            conditions.update(found)
    except Exception as exc:
        log.warning("alert rule platform jobs could not be read: %s", type(exc).__name__)
        protected += [("job_failed", "platform"), ("stuck_job", "platform")]
    try:
        found = _eval_regression(reports_dir or Path(settings.alert_eval_reports_dir), settings)
    except Exception as exc:
        log.warning("alert rule eval_regression could not be read: %s", type(exc).__name__)
        found = None
    if found is None:
        evaluated.discard("eval_regression")
    else:
        conditions.update(found)
    return reconcile(engine, conditions, evaluated, now, protected)
