"""Logs and alerts (S9.4). Tests run for every tenant folder and never name one."""

import logging
import random
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.core import error_log
from app.core.db import ENGINE_OPTIONS, tenant_session
from app.core.error_log import ErrorLogHandler, install_error_log_handler
from app.core.models import AuditEvent, Case, JobRun, LlmUsage
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


_OWNER = []


def owner():
    """The owner role: the app role has no grant on alerts or error_logs, so tests read them
    as the owner."""
    if not _OWNER:
        _OWNER.append(create_engine(get_settings().test_migration_database_url, **ENGINE_OPTIONS))
    return _OWNER[0]


def alert_rows(_engine=None):
    with owner().connect() as c:
        return c.execute(text("SELECT rule, scope, status, value FROM alerts")).all()


def open_rules(_engine=None):
    return sorted((r.rule, r.scope) for r in alert_rows() if r.status == "open")


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
    with pytest.raises(Exception, match="uq_alerts_one_open"), owner().begin() as c:
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


def _escalated(engine, tid, n, occurred_at):
    """n distinct cases that escalated at `occurred_at` (audit events; the cases may have been
    resolved since, which is the point)."""
    with tenant_session(tid, engine) as s:
        for _ in range(n):
            s.add(
                AuditEvent(
                    tenant_id=tid, actor_type="system", event="case.escalated",
                    entity_type="case", entity_id=uuid.uuid4(), occurred_at=occurred_at,
                )
            )  # fmt: skip


def _far_future():
    """Audit events cannot be deleted, so each run uses its own distant 'now' and never meets
    another run's (or real) events."""
    return datetime.now(UTC) + timedelta(days=random.randint(5_000, 60_000))


def test_escalation_spike_fires_against_a_quiet_week_and_clears_when_it_passes(app_engine, tid):
    now = _far_future()
    _escalated(app_engine, tid, get_settings().alert_escalation_min_count, now - timedelta(hours=2))
    run(app_engine, tid, now=now)
    assert [r for r, _ in open_rules()] == ["escalation_spike"]
    run(app_engine, tid, now=now + timedelta(days=2))  # outside the 24h window now
    assert open_rules() == []


def test_a_busy_normal_week_is_not_a_spike(app_engine, tid):
    now = _far_future()
    n = get_settings().alert_escalation_min_count
    for d in range(2, 9):  # every prior day had as many as today
        _escalated(app_engine, tid, n, now - timedelta(days=d, hours=1))
    _escalated(app_engine, tid, n, now - timedelta(hours=2))
    assert run(app_engine, tid, now=now)["opened"] == 0


REPORT = (
    "# Eval report x\n\n- set: {set}\n- models: {models}\n\n"
    "| tenant | pipeline | n | pass | class |\n|---|---|---|---|---|\n"
    "| t_one | multi | 20 | {a}% | 90% |\n| t_two | single | 20 | {b}% | 90% |\n\nLegend\n"
)


def _report(d: Path, name: str, a: int, b: int, set="tuning", models="m1") -> None:
    (d / name).write_text(REPORT.format(a=a, b=b, set=set, models=models), encoding="utf-8")


def test_eval_regression_compares_latest_report_with_the_previous(app_engine, tid, tmp_path):
    _report(tmp_path, "eval-2026-01-01.md", 90, 80)
    assert run(app_engine, tid, reports_dir=tmp_path)["opened"] == 0  # one report only
    _report(tmp_path, "eval-2026-01-02.md", 70, 79)  # t_one drops 20, t_two drops 1
    run(app_engine, tid, reports_dir=tmp_path)
    assert open_rules() == [("eval_regression", "t_one/multi")]
    _report(tmp_path, "eval-2026-01-03.md", 72, 79)  # recovered relative to the last one
    run(app_engine, tid, reports_dir=tmp_path)
    assert open_rules() == []


def test_missing_reports_folder_is_no_alert_and_no_error(app_engine, tid, tmp_path):
    assert run(app_engine, tid, reports_dir=tmp_path / "nope")["opened"] == 0


def _open_eval_alert(app_engine, tid, tmp_path):
    _report(tmp_path, "eval-2026-01-01.md", 90, 80)
    _report(tmp_path, "eval-2026-01-02.md", 70, 80)
    run(app_engine, tid, reports_dir=tmp_path)
    assert open_rules() == [("eval_regression", "t_one/multi")]


def test_an_eval_rule_that_could_not_compare_resolves_nothing(app_engine, tid, tmp_path):
    _open_eval_alert(app_engine, tid, tmp_path)
    run(app_engine, tid, reports_dir=tmp_path / "gone")  # folder missing
    assert len(open_rules()) == 1
    other = tmp_path / "one"
    other.mkdir()
    _report(other, "eval-2026-01-01.md", 90, 80)  # fewer than two reports
    run(app_engine, tid, reports_dir=other)
    assert len(open_rules()) == 1


def test_an_eval_report_with_no_rows_resolves_nothing(app_engine, tid, tmp_path):
    _open_eval_alert(app_engine, tid, tmp_path)
    (tmp_path / "eval-2026-01-03.md").write_text("# Eval report\n\n- set: tuning\n- models: m1\n")
    run(app_engine, tid, reports_dir=tmp_path)
    assert len(open_rules()) == 1


def test_reports_of_a_different_set_or_model_are_not_compared(app_engine, tid, tmp_path):
    _report(tmp_path, "eval-2026-01-01.md", 90, 80, set="all")
    _report(tmp_path, "eval-2026-01-02.md", 50, 80, set="held-out")  # a smaller set: not a drop
    assert run(app_engine, tid, reports_dir=tmp_path)["opened"] == 0
    _report(tmp_path, "eval-2026-01-03.md", 40, 80, set="held-out", models="m2")  # other model
    assert run(app_engine, tid, reports_dir=tmp_path)["opened"] == 0
    _report(tmp_path, "eval-2026-01-04.md", 30, 80, set="held-out", models="m2")
    run(app_engine, tid, reports_dir=tmp_path)
    assert open_rules() == [("eval_regression", "t_one/multi")]  # same set and model: a drop


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
    with owner().connect() as c:
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


def rows(_engine=None):
    with owner().connect() as c:
        return c.execute(
            text("SELECT service, level, event_code, error_class, occurrences FROM error_logs")
        ).all()


class DeadEngine:
    """An engine whose database is down: every connection attempt fails at once."""

    def begin(self):
        raise OperationalError("SELECT 1", {}, ConnectionError("down"))


class SpyEngine:
    """Records which thread asks for a connection, and then fails."""

    def __init__(self):
        self.threads = []

    def begin(self):
        self.threads.append(threading.get_ident())
        raise OperationalError("SELECT 1", {}, ConnectionError("down"))


def make_logger(handler, name="app.s94.sample"):
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg.addHandler(handler)
    return lg


def test_error_log_stores_codes_and_counts_never_the_message(app_engine, tid):
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
    handler.process(force=True)
    with owner().connect() as c:
        dump = c.execute(text("SELECT row_to_json(e)::text FROM error_logs e")).scalars().all()
        cols = (
            c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='error_logs'"
                )
            )
            .scalars()
            .all()
        )
    blob = " ".join(dump)
    assert dump and not any(p in blob for p in PII)
    assert "tenant_id" not in cols
    got = {(r.service, r.level, r.event_code, r.error_class) for r in rows()}
    assert ("s94", "ERROR", "app.s94.sample", "ValueError") in got
    assert ("s94", "CRITICAL", "app.s94.sample", "") in got


def test_event_code_and_class_must_look_like_identifiers(app_engine, tid):
    class Weird(Exception):
        pass

    Weird.__name__ = "Bad Name 9876543210"
    handler = ErrorLogHandler(app_engine, 10.0, Clock())
    lg = make_logger(handler, "app.s94.Odd Name 9876543210")
    other = make_logger(handler, "somethingelse.s94")
    try:
        lg.error("x", exc_info=Weird("y"))
        other.error("x")
    finally:
        lg.removeHandler(handler)
        other.removeHandler(handler)
    handler.process(force=True)
    got = {(r.event_code, r.error_class) for r in rows()}
    assert got == {("unknown", "unknown"), ("unknown", "")}


def test_error_log_aggregates_a_storm_into_one_write_per_interval(tid):
    clock, engine = Clock(), SpyEngine()
    handler = ErrorLogHandler(engine, 10.0, clock)
    lg = make_logger(handler)
    try:
        for _ in range(500):
            lg.error("boom")
        handler.process()
        assert engine.threads == []  # interval not over: counted, not written
        clock.t += 11
        handler.process()
        assert len(engine.threads) == 1  # 500 events, one write
    finally:
        lg.removeHandler(handler)


def test_the_counts_reach_the_table_as_one_row(app_engine, tid):
    clock = Clock()
    handler = ErrorLogHandler(app_engine, 10.0, clock)
    lg = make_logger(handler)
    try:
        for _ in range(500):
            lg.error("boom")
    finally:
        lg.removeHandler(handler)
    clock.t += 11
    handler.process()
    assert [r.occurrences for r in rows()] == [500]


def test_emit_never_touches_the_database_on_the_calling_thread(tid):
    engine = SpyEngine()
    handler = ErrorLogHandler(engine, 0.0)
    lg = make_logger(handler)
    try:
        for _ in range(20):
            lg.error("boom")
        assert engine.threads == []  # nothing happened synchronously
        handler.start()
        for _ in range(100):  # the drain thread writes on its own, within a moment
            if engine.threads:
                break
            threading.Event().wait(0.05)
        written_by = set(engine.threads)  # before shutdown (which flushes on the caller)
    finally:
        lg.removeHandler(handler)
        handler.flush_pending()
    assert written_by and threading.get_ident() not in written_by


def test_emit_does_not_wait_on_a_database_that_hangs(tid):
    release = threading.Event()

    class Hanging:
        def begin(self):
            release.wait(5)
            raise OperationalError("SELECT 1", {}, ConnectionError("hang"))

    handler = ErrorLogHandler(Hanging(), 0.0)
    handler.start()
    lg = make_logger(handler)
    started = datetime.now(UTC)
    try:
        for _ in range(50):
            lg.error("boom")
        assert (datetime.now(UTC) - started).total_seconds() < 1.0
    finally:
        lg.removeHandler(handler)
        release.set()
        handler.flush_pending()


def test_a_full_queue_drops_and_counts_the_drops(app_engine, tid):
    handler = ErrorLogHandler(app_engine, 10.0, Clock(), queue_size=5)
    lg = make_logger(handler)
    try:
        for _ in range(12):
            lg.error("boom")
    finally:
        lg.removeHandler(handler)
    assert handler.dropped == 7
    handler.process(force=True)
    got = {r.event_code: r.occurrences for r in rows()}
    assert got == {"app.s94.sample": 5, "dropped": 7}


def test_flush_pending_writes_what_was_held_back(app_engine, tid):
    handler = ErrorLogHandler(app_engine, 10.0, Clock())
    lg = make_logger(handler)
    try:
        for _ in range(5):
            lg.error("boom")
    finally:
        lg.removeHandler(handler)
    handler.flush_pending()
    assert [r.occurrences for r in rows()] == [5]


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
    handler.process(force=True)
    got = rows()
    assert len(got) <= 4
    assert any(r.event_code == "overflow" for r in got)
    assert sum(r.occurrences for r in got) == 10


def test_a_handler_whose_database_is_down_never_raises_or_recurses(tid):
    handler = ErrorLogHandler(DeadEngine(), 0.0, Clock())
    parent = logging.getLogger("app")
    parent.addHandler(handler)  # also sees the handler's own warning: it must not loop
    lg = make_logger(handler)
    try:
        for _ in range(3):
            lg.error("boom", exc_info=ValueError("x"))
        handler.process(force=True)
        assert handler._queue.qsize() == 0  # its own warning was not queued again
    finally:
        lg.removeHandler(handler)
        parent.removeHandler(handler)


def test_a_failing_log_handler_does_not_break_a_request(tid):
    app = FastAPI()
    lg = logging.getLogger("app.s94.route")

    @app.get("/x")
    def x():
        lg.error("this request logs an error", exc_info=RuntimeError("seen"))
        return {"ok": True}

    uninstall = install_error_log_handler(DeadEngine(), 0.0, dedicated=False)
    try:
        resp = TestClient(app).get("/x")
    finally:
        uninstall()
    assert resp.status_code == 200 and resp.json() == {"ok": True}


def test_the_dedicated_engine_is_one_connection_with_short_timeouts(app_engine):
    uninstall = install_error_log_handler(app_engine, 10.0)
    try:
        handler = next(
            h for h in logging.getLogger("app").handlers if isinstance(h, ErrorLogHandler)
        )
        pool = handler.engine.pool
        assert (pool.size(), pool._max_overflow, pool._timeout) == (1, 0, 2)
        assert handler.engine is not app_engine
    finally:
        uninstall()


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


# --- the app role cannot read these tables (B2) ------------------------------------------


@pytest.mark.parametrize(
    "stmt",
    [
        "SELECT 1 FROM error_logs",
        "DELETE FROM error_logs",
        "UPDATE error_logs SET day = day",
        "INSERT INTO error_logs (service) VALUES ('x')",
        "SELECT 1 FROM alerts",
        "DELETE FROM alerts",
        "UPDATE alerts SET rule = rule",
        "INSERT INTO alerts (rule) VALUES ('x')",
    ],
)
def test_the_app_role_has_no_grant_on_the_log_and_alert_tables(app_engine, stmt):
    with pytest.raises(Exception, match="permission denied"), app_engine.begin() as c:
        c.execute(text(stmt))


def test_tenant_request_code_cannot_read_alert_scopes(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    run(app_engine, tid)
    assert open_rules()  # the owner sees them
    with pytest.raises(Exception, match="permission denied"), tenant_session(tid, app_engine) as s:
        s.execute(text("SELECT scope FROM alerts"))


def test_the_functions_are_executable_by_the_app_role_and_not_by_public(app_engine):
    with owner().connect() as c:
        got = c.execute(
            text(
                "SELECT p.proname, p.prosecdef, p.proconfig::text, "
                "has_function_privilege('resolvedesk_app', p.oid, 'EXECUTE'), "
                "has_function_privilege('public', p.oid, 'EXECUTE') "
                "FROM pg_proc p WHERE p.proname IN ('alerts_apply', 'log_error_count')"
            )
        ).all()
    assert {r[0] for r in got} == {"alerts_apply", "log_error_count"}
    for _, definer, config, app, public in got:
        assert definer and "search_path" in config and app and not public


# --- one tenant's failed read protects only that tenant ----------------------------------


def test_one_tenants_failed_read_leaves_only_its_alerts_alone(app_engine, tid, seeded_history):
    other = next(
        tenant_id_for(c.slug) for c in seeded_history.values() if tenant_id_for(c.slug) != tid
    )
    fail_job(app_engine, tid, "s94_job")
    fail_job(app_engine, other, "s94_job")
    evaluate_alerts(app_engine, [tid, other], get_settings())
    assert len(open_rules()) == 2
    fail_job(app_engine, tid, "s94_job", "ok")
    fail_job(app_engine, other, "s94_job", "ok")
    real = alerts_mod.TENANT_RULES["job_failed"]

    def flaky(session, slug, now, s):
        # Fails only for the other tenant (its session sees only its own job rows).
        if session.execute(select(JobRun.tenant_id).limit(1)).scalar() == other:
            raise RuntimeError("hiccup")
        return real(session, slug, now, s)

    alerts_mod.TENANT_RULES["job_failed"] = flaky
    try:
        evaluate_alerts(app_engine, [tid, other], get_settings())
    finally:
        alerts_mod.TENANT_RULES["job_failed"] = real
    assert len(open_rules()) == 1  # this tenant's cleared, the unreadable one's stays


def test_opened_counts_only_real_inserts(app_engine, tid):
    fail_job(app_engine, tid, "s94_job")
    assert run(app_engine, tid)["opened"] == 1
    assert run(app_engine, tid)["opened"] == 0
