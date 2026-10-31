"""Logs and alerts (S9.4). Tests run for every tenant folder and never name one."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.core import error_log
from app.core.db import tenant_session
from app.core.error_log import ErrorLogHandler, install_error_log_handler
from app.core.models import Case, Customer, JobRun, LlmUsage
from app.core.telemetry import finish_job, finish_platform_job, start_job, start_platform_job
from app.core.tenancy import tenant_id_for
from app.engine import alerts as alerts_mod
from app.engine.alerts import evaluate_alerts

PII = ["9876543210", "Asha Rao", "asha@example.test", "Bearer abc.def.ghi", "12 Hidden Lane"]


@pytest.fixture
def tid(seeded_history, tenant, maint_engine, owner_engine):
    tid = tenant_id_for(seeded_history[tenant.name].slug)

    def clean():
        with tenant_session(tid, maint_engine) as s:
            s.execute(delete(JobRun).where(JobRun.tenant_id == tid))
            s.execute(delete(LlmUsage).where(LlmUsage.tenant_id == tid))
            s.execute(delete(Case).where(Case.category == "s94_alert_test"))
        with owner_engine.begin() as c:
            c.execute(text("DELETE FROM alerts"))
            c.execute(text("DELETE FROM platform_job_runs"))
            c.execute(text("DELETE FROM error_logs"))

    clean()
    yield tid
    clean()


def run(app_engine, tid, **kw):
    return evaluate_alerts(app_engine, [tid], get_settings(), **kw)


def alert_rows(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT rule, scope, status, value FROM alerts")).all()


def open_rules(engine):
    return sorted((r.rule, r.scope) for r in alert_rows(engine) if r.status == "open")


def fail_job(engine, tid, job, status="failed"):
    finish_job(engine, tid, start_job(engine, tid, job), status, error_class="Boom")


# --- rules fire and clear ----------------------------------------------------------------


def test_job_failed_fires_then_clears_when_the_next_run_is_ok(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    assert run(app_engine, tid)["opened"] == 1
    [(rule, scope)] = open_rules(app_engine)
    assert rule == "job_failed" and scope.endswith(":s94_job")
    fail_job(app_engine, tid, "s94_job", "ok")
    assert run(app_engine, tid)["resolved"] == 1
    assert open_rules(app_engine) == []
    assert [r.status for r in alert_rows(app_engine)] == ["resolved"]


def test_an_old_failure_outside_the_lookback_does_not_alert(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    later = datetime.now(UTC) + timedelta(hours=get_settings().alert_job_lookback_hours + 1)
    assert run(app_engine, tid, now=later)["opened"] == 0


def test_the_same_condition_updates_one_alert_and_never_duplicates(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    first = run(app_engine, tid)
    second = run(app_engine, tid)
    third = run(app_engine, tid)
    assert (first["opened"], second["opened"], third["opened"]) == (1, 0, 0)
    assert third["refreshed"] == 1
    assert len(alert_rows(app_engine)) == 1


def test_the_database_refuses_two_open_alerts_for_one_condition(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    run(app_engine, tid)
    with pytest.raises(Exception, match="uq_alerts_one_open"), app_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO alerts (rule, scope, status, value, threshold, opened_at, "
                "last_seen_at) SELECT rule, scope, 'open', 1, 1, now(), now() FROM alerts"
            )
        )


def test_a_closed_alert_can_open_again_as_a_new_row(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    run(app_engine, tid)
    fail_job(app_engine, tid, "s94_job", "ok")
    run(app_engine, tid)
    fail_job(app_engine, tid, "s94_job")
    assert run(app_engine, tid)["opened"] == 1
    assert sorted(r.status for r in alert_rows(app_engine)) == ["open", "resolved"]


def test_platform_job_failure_fires_and_clears(app_engine, tid):
    finish_platform_job(app_engine, start_platform_job(app_engine, "s94_pj"), "failed", None, "X")
    run(app_engine, tid)
    assert ("job_failed", "platform:s94_pj") in open_rules(app_engine)
    finish_platform_job(app_engine, start_platform_job(app_engine, "s94_pj"), "ok")
    run(app_engine, tid)
    assert ("job_failed", "platform:s94_pj") not in open_rules(app_engine)


def test_stuck_job_fires_when_running_too_long_and_clears_when_it_ends(app_engine, tid):
    job_id = start_job(app_engine, tid, "s94_sweep")
    assert run(app_engine, tid)["opened"] == 0  # just started: not stuck
    later = datetime.now(UTC) + timedelta(minutes=get_settings().alert_stuck_minutes + 5)
    run(app_engine, tid, now=later)
    assert [r for r, _ in open_rules(app_engine)] == ["stuck_job"]
    finish_job(app_engine, tid, job_id, "ok")
    run(app_engine, tid, now=later)
    assert open_rules(app_engine) == []


def _usage(engine, tid, calls, failures):
    with tenant_session(tid, engine) as s:
        s.add(
            LlmUsage(
                tenant_id=tid, role="main", provider="p", model="m", calls=calls,
                input_tokens=0, output_tokens=0, estimated_cost_micro_paise=0,
                failures=failures, latency_ms=0, outcome="ok",
            )
        )  # fmt: skip


def test_provider_failure_rate_fires_above_threshold_and_clears_when_it_drops(app_engine, tid):
    s = get_settings()
    _usage(app_engine, tid, 10, 1)  # 10%: under the default threshold
    assert run(app_engine, tid)["opened"] == 0
    _usage(app_engine, tid, 10, 9)  # now 10 of 20 = 50%
    run(app_engine, tid)
    [row] = [r for r in alert_rows(app_engine) if r.rule == "provider_failure_rate"]
    assert row.value == 5000
    _usage(app_engine, tid, 1000, 0)  # 10 of 1020: under again
    run(app_engine, tid)
    assert open_rules(app_engine) == []
    assert s.alert_provider_failure_bps == 2000


def test_provider_failure_rate_needs_a_minimum_number_of_calls(app_engine, tid):
    _usage(app_engine, tid, 3, 3)  # 100% of almost nothing
    assert run(app_engine, tid)["opened"] == 0


def _escalated(engine, tid, n, opened_at):
    with tenant_session(tid, engine) as s:
        customer_id = s.execute(select(Customer.id).limit(1)).scalar_one()
        for _ in range(n):
            s.add(
                Case(
                    tenant_id=tid, customer_id=customer_id, status="escalated", channel="app",
                    category="s94_alert_test", opened_at=opened_at,
                )
            )  # fmt: skip


def test_escalation_spike_fires_against_a_quiet_week_and_clears_when_it_passes(app_engine, tid):
    now = datetime.now(UTC)
    _escalated(app_engine, tid, get_settings().alert_escalation_min_count, now - timedelta(hours=2))
    run(app_engine, tid)
    assert [r for r, _ in open_rules(app_engine)] == ["escalation_spike"]
    run(app_engine, tid, now=now + timedelta(days=2))  # they are now outside the 24h window
    assert open_rules(app_engine) == []


def test_a_busy_normal_week_is_not_a_spike(app_engine, tid):
    now = datetime.now(UTC)
    n = get_settings().alert_escalation_min_count
    for d in range(2, 9):  # every prior day had as many as today
        _escalated(app_engine, tid, n, now - timedelta(days=d, hours=1))
    _escalated(app_engine, tid, n, now - timedelta(hours=2))
    assert run(app_engine, tid)["opened"] == 0


REPORT = (
    "# Eval report x\n\n| tenant | pipeline | n | pass | class |\n|---|---|---|---|---|\n"
    "| t_one | multi | 20 | {a}% | 90% |\n| t_two | single | 20 | {b}% | 90% |\n\nLegend\n"
)


def _report(d: Path, name: str, a: int, b: int) -> None:
    (d / name).write_text(REPORT.format(a=a, b=b), encoding="utf-8")


def test_eval_regression_compares_latest_report_with_the_previous(app_engine, tid, tmp_path):
    _report(tmp_path, "eval-2026-01-01.md", 90, 80)
    assert (
        run(app_engine, tid, reports_dir=tmp_path)["opened"] == 0
    )  # one report: nothing to compare
    _report(tmp_path, "eval-2026-01-02.md", 70, 79)  # t_one drops 20, t_two drops 1
    run(app_engine, tid, reports_dir=tmp_path)
    assert open_rules(app_engine) == [("eval_regression", "t_one/multi")]
    _report(tmp_path, "eval-2026-01-03.md", 72, 79)  # recovered relative to the last one
    run(app_engine, tid, reports_dir=tmp_path)
    assert open_rules(app_engine) == []


def test_missing_reports_folder_is_no_alert_and_no_error(app_engine, tid, tmp_path):
    assert run(app_engine, tid, reports_dir=tmp_path / "nope")["opened"] == 0


def test_a_rule_that_cannot_be_read_does_not_clear_its_alerts(app_engine, tid, monkeypatch):
    fail_job(app_engine, tid, "s94_job")
    run(app_engine, tid)
    assert len(open_rules(app_engine)) == 1

    def broken(*a, **k):
        raise RuntimeError("database hiccup")

    monkeypatch.setitem(alerts_mod.TENANT_RULES, "job_failed", broken)
    run(app_engine, tid)
    assert len(open_rules(app_engine)) == 1  # unknown is not "cleared"


def test_thresholds_come_from_settings(app_engine, tid, monkeypatch):
    _usage(app_engine, tid, 10, 1)  # 10%
    monkeypatch.setenv("ALERT_PROVIDER_FAILURE_BPS", "500")
    get_settings.cache_clear()
    try:
        run(app_engine, tid)
        assert [r for r, _ in open_rules(app_engine)] == ["provider_failure_rate"]
    finally:
        monkeypatch.delenv("ALERT_PROVIDER_FAILURE_BPS")
        get_settings.cache_clear()


def test_alerts_hold_no_text_beyond_codes_and_numbers(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    run(app_engine, tid)
    with app_engine.connect() as c:
        cols = {
            r[0]: r[1]
            for r in c.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'alerts'"
                )
            )
        }
    assert "tenant_id" not in cols
    assert {k for k, v in cols.items() if v == "text"} == set()


def test_the_rules_read_only_the_tenants_they_are_given(app_engine, tid, seeded_history):
    """Each tenant is read through its own RLS session: a failure in another tenant is invisible
    to an evaluation that was not given that tenant."""
    others = [
        tenant_id_for(c.slug) for c in seeded_history.values() if tenant_id_for(c.slug) != tid
    ]
    assert others
    fail_job(app_engine, tid, "s94_job")
    assert evaluate_alerts(app_engine, others, get_settings())["opened"] == 0
    assert evaluate_alerts(app_engine, [tid], get_settings())["opened"] == 1


# --- error log ---------------------------------------------------------------------------


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def rows(engine):
    with engine.connect() as c:
        return c.execute(
            text("SELECT service, level, event_code, error_class, occurrences FROM error_logs")
        ).all()


class DeadEngine:
    """An engine whose database is down: every connection attempt fails at once."""

    def begin(self):
        raise OperationalError("SELECT 1", {}, ConnectionError("down"))


def make_logger(handler, name="app.s94.sample"):
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg.addHandler(handler)
    return lg


def test_error_log_stores_codes_and_counts_never_the_message(app_engine, tid, owner_engine):
    handler = ErrorLogHandler(app_engine, 10.0, Clock())
    lg = make_logger(handler)
    try:
        try:
            raise ValueError(" ".join(PII))
        except ValueError:
            lg.error("refund for %s failed: %s", PII[1], PII[0], exc_info=True)
        lg.critical("token %s", PII[3], extra={"phone": PII[0]})
    finally:
        lg.removeHandler(handler)
    with owner_engine.connect() as c:
        dump = c.execute(text("SELECT row_to_json(e)::text FROM error_logs e")).scalars().all()
        cols = c.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='error_logs'"
            )
        ).scalars().all()  # fmt: skip
    blob = " ".join(dump)
    assert dump and not any(p in blob for p in PII)
    assert "tenant_id" not in cols
    got = {(r.service, r.level, r.event_code, r.error_class) for r in rows(app_engine)}
    assert ("s94", "ERROR", "app.s94.sample", "ValueError") in got
    assert ("s94", "CRITICAL", "app.s94.sample", "") in got


def test_error_log_rate_limits_a_storm_into_a_few_writes(app_engine, tid):
    clock = Clock()
    handler = ErrorLogHandler(app_engine, 10.0, clock)
    writes = []
    real = handler._write
    handler._write = lambda key, n: (writes.append(n), real(key, n))[1]
    lg = make_logger(handler)
    try:
        for _ in range(500):
            lg.error("boom")
        assert writes == [1]  # first at once, the rest only counted
        clock.t += 11
        lg.error("boom")
        assert writes == [1, 500]  # 499 held + this one
    finally:
        lg.removeHandler(handler)
    assert [r.occurrences for r in rows(app_engine)] == [501]


def test_flush_pending_writes_what_was_held_back(app_engine, tid):
    handler = ErrorLogHandler(app_engine, 10.0, Clock())
    lg = make_logger(handler)
    try:
        for _ in range(5):
            lg.error("boom")
    finally:
        lg.removeHandler(handler)
    handler.flush_pending()
    assert [r.occurrences for r in rows(app_engine)] == [5]


def test_distinct_error_types_are_capped_so_the_table_cannot_fill(app_engine, tid, monkeypatch):
    monkeypatch.setattr(error_log, "MAX_KEYS_PER_DAY", 3)
    handler = ErrorLogHandler(app_engine, 0.0, Clock())
    loggers = [make_logger(handler, f"app.s94.many{i}") for i in range(10)]
    try:
        for lg in loggers:
            lg.error("boom")
    finally:
        for lg in loggers:
            lg.removeHandler(handler)
    got = rows(app_engine)
    assert len(got) <= 4
    assert any(r.event_code == "overflow" for r in got)
    assert sum(r.occurrences for r in got) == 10


def test_a_handler_whose_database_is_down_never_raises_or_recurses(tid):
    dead = DeadEngine()
    handler = ErrorLogHandler(dead, 0.0, Clock())
    parent = logging.getLogger("app")
    parent.addHandler(handler)  # also sees the handler's own warning: it must not loop
    lg = make_logger(handler)
    try:
        for _ in range(3):
            lg.error("boom", exc_info=ValueError("x"))
    finally:
        lg.removeHandler(handler)
        parent.removeHandler(handler)


def test_a_failing_log_handler_does_not_break_a_request(tid):
    dead = DeadEngine()
    app = FastAPI()
    lg = logging.getLogger("app.s94.route")

    @app.get("/x")
    def x():
        lg.error("this request logs an error", exc_info=RuntimeError("seen"))
        return {"ok": True}

    uninstall = install_error_log_handler(dead, 0.0)
    try:
        resp = TestClient(app).get("/x")
    finally:
        uninstall()
    assert resp.status_code == 200 and resp.json() == {"ok": True}


def test_the_alerts_job_is_registered_and_off_when_its_interval_is_zero(app_engine, monkeypatch):
    from app.engine.scheduled_jobs import build_jobs

    jobs = {j.name: j for j in build_jobs(get_settings(), app_engine)}
    assert jobs["alerts"].interval > 0 and jobs["alerts"].tenant_ids is None
    monkeypatch.setenv("SCHEDULER_ALERTS_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    try:
        off = {j.name: j for j in build_jobs(get_settings(), app_engine)}["alerts"]
        assert off.interval == 0
    finally:
        monkeypatch.delenv("SCHEDULER_ALERTS_INTERVAL_SECONDS")
        get_settings.cache_clear()


def test_the_app_role_cannot_delete_logs_or_alerts(app_engine, tid):
    for table in ("error_logs", "alerts"):
        with pytest.raises(Exception, match="permission denied"), app_engine.begin() as c:
            c.execute(text(f"DELETE FROM {table}"))
