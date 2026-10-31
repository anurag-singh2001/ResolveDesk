"""Persisted LLM usage and job runs (S9.2), for every tenant: recorded per tenant under RLS,
never any text, and a recording failure never breaks the run or the job."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

import app.core.telemetry as telemetry
from app.config import Settings
from app.core.db import tenant_session
from app.core.models import JobRun, LlmUsage
from app.core.tenancy import tenant_id_for
from app.engine import graph
from app.engine.retention import purge_all
from app.engine.sweeper import sweep_all
from app.llm.providers import RunBudget
from app.modules.growth import signals

SECRET = "refund me 9876543210 at 12 Hidden Lane"


@pytest.fixture
def tid(seeded, tenant, maint_engine):
    tid = tenant_id_for(seeded[tenant.name].slug)
    yield tid
    for model in (LlmUsage, JobRun):  # the app role cannot delete: the maintenance role does
        for t in {tenant_id_for(c.slug) for c in seeded.values()}:
            with tenant_session(t, maint_engine) as s:
                s.execute(delete(model).where(model.tenant_id == t))


def budget_with_usage(fail_first=False) -> RunBudget:
    b = RunBudget(max_calls=8)
    if fail_first:
        b.note_request("main", "p", "m1", latency_ms=5, error_class="RuntimeError")
    b.note_request(
        "main", "f" if fail_first else "p", "m2", latency_ms=7, input_tokens=11, output_tokens=3,
        fallback=fail_first,
    )  # fmt: skip
    return b


def rows(engine, tid, model):
    with tenant_session(tid, engine) as s:
        found = s.scalars(select(model).where(model.tenant_id == tid)).all()
        return [  # plain copies: the ORM objects expire when the session commits
            SimpleNamespace(**{c.name: getattr(r, c.name) for c in model.__table__.columns})
            for r in found
        ]


def test_run_usage_is_recorded_for_its_tenant_only(app_engine, tid, seeded):
    run_id = uuid.uuid4()
    telemetry.record_llm_usage(app_engine, tid, budget_with_usage(fail_first=True), run_id)
    got = {r.model: r for r in rows(app_engine, tid, LlmUsage)}
    assert got["m1"].outcome == "error" and got["m1"].error_class == "RuntimeError"
    assert got["m2"].outcome == "fallback_used" and got["m2"].input_tokens == 11
    assert all(r.run_id == run_id and r.tenant_id == tid for r in got.values())
    for other in {tenant_id_for(c.slug) for c in seeded.values()} - {tid}:
        assert rows(app_engine, other, LlmUsage) == []


def test_cost_estimate_is_stored_as_integer_micro_paise(app_engine, tid):
    s = Settings(_env_file=None, app_env="test", llm_prices_paise_per_million={"p/m2": (10, 20)})
    telemetry.record_llm_usage(app_engine, tid, budget_with_usage(), settings=s)
    (r,) = rows(app_engine, tid, LlmUsage)
    assert r.estimated_cost_micro_paise == 11 * 10 + 3 * 20 and r.run_id is None


def test_no_text_is_stored_in_any_column(app_engine, tid):
    b = RunBudget(max_calls=8)
    b.note_request("main", "p", "m", latency_ms=1, error_class="ValueError")
    telemetry.record_llm_usage(app_engine, tid, b)
    job = telemetry.start_job(app_engine, tid, "sweep")
    telemetry.finish_job(app_engine, tid, job, "failed", {"n": 1}, "ValueError")
    for model in (LlmUsage, JobRun):
        for r in rows(app_engine, tid, model):
            blob = " ".join(str(getattr(r, c.name)) for c in model.__table__.columns)
            assert SECRET not in blob and "9876543210" not in blob
        # no unbounded text column exists that could take a prompt or a reply
        unbounded = [
            c.name
            for c in model.__table__.columns
            if hasattr(c.type, "length") and c.type.length is None and c.type.python_type is str
        ]
        assert unbounded == []


def test_recording_failure_does_not_break_the_run(app_engine, tid, monkeypatch, caplog):
    def broken(*a, **k):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(telemetry, "tenant_session", broken)
    deps = SimpleNamespace(engine=app_engine)
    out = graph._record(deps, tid, uuid.uuid4(), {"outcome": "ok"}, False, budget_with_usage())
    assert isinstance(out, dict)
    telemetry.record_llm_usage(app_engine, tid, budget_with_usage())  # does not raise
    assert SECRET not in caplog.text  # only the exception class is logged
    assert rows(app_engine, tid, LlmUsage) == []


def test_run_record_writes_usage_after_its_transaction_closed(app_engine, tid):
    deps = SimpleNamespace(engine=app_engine)
    graph._record(deps, tid, uuid.uuid4(), {"outcome": "ok"}, False, budget_with_usage())
    assert len(rows(app_engine, tid, LlmUsage)) == 1


def test_job_run_records_ok_with_counts_and_failed_with_class(app_engine, tid):
    result = telemetry.run_job(app_engine, tid, "j_ok", lambda: [1, 2], lambda r: {"n": len(r)})
    assert result == [1, 2]

    def boom():
        raise KeyError(SECRET)

    with pytest.raises(KeyError):
        telemetry.run_job(app_engine, tid, "j_bad", boom)
    got = {r.job: r for r in rows(app_engine, tid, JobRun)}
    assert got["j_ok"].status == "ok" and got["j_ok"].counts == {"n": 2}
    assert got["j_ok"].finished_at >= got["j_ok"].started_at
    assert got["j_bad"].status == "failed" and got["j_bad"].error_class == "KeyError"
    assert SECRET not in str(got["j_bad"].counts)


def test_job_runs_even_if_recording_fails(app_engine, tid, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(telemetry, "tenant_session", broken)
    assert telemetry.run_job(app_engine, tid, "j", lambda: 7) == 7
    with pytest.raises(ZeroDivisionError):  # the job's own error still reaches the caller
        telemetry.run_job(app_engine, tid, "j", lambda: 1 / 0)


def test_sweep_retention_and_growth_nightly_are_recorded(app_engine, tid):
    sweep_all(app_engine)
    purge_all(app_engine)  # dry run
    signals.run_nightly(app_engine, tid, datetime.now(UTC))
    got = {r.job: r for r in rows(app_engine, tid, JobRun)}
    jobs = ("sweep", "retention_dry_run", "growth_nightly")
    assert set(jobs) <= set(got) and all(got[j].status == "ok" for j in jobs)
    assert "escalated_cases" in got["sweep"].counts
    assert "messages" in got["retention_dry_run"].counts
    assert "signals" in got["growth_nightly"].counts


def test_app_role_cannot_rewrite_usage_or_the_start_of_a_job(app_engine, tid):
    telemetry.record_llm_usage(app_engine, tid, budget_with_usage())
    job = telemetry.start_job(app_engine, tid, "sweep")
    for sql in (
        "UPDATE llm_usage SET calls = 99",
        "DELETE FROM llm_usage",
        "DELETE FROM job_runs",
        "UPDATE job_runs SET job = 'x'",
        "UPDATE job_runs SET started_at = now()",
    ):
        with (
            pytest.raises(DBAPIError, match="permission denied"),
            tenant_session(tid, app_engine) as s,
        ):
            s.execute(text(sql))
    telemetry.finish_job(app_engine, tid, job, "ok", {"n": 1})  # the finish columns are allowed
    assert [r.status for r in rows(app_engine, tid, JobRun)] == ["ok"]


def test_next_start_closes_a_stale_running_row_as_abandoned(app_engine, maint_engine, tid):
    old = telemetry.start_job(app_engine, tid, "sweep")
    recent = telemetry.start_job(app_engine, tid, "sweep")  # not past the TTL: left alone
    other = telemetry.start_job(app_engine, tid, "retention_dry_run")
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            text("UPDATE job_runs SET started_at = :t WHERE id = :i"),
            {"t": datetime.now(UTC) - telemetry.ABANDON_AFTER - timedelta(minutes=1), "i": old},
        )
    new = telemetry.start_job(app_engine, tid, "sweep")
    by_id = {r.id: r for r in rows(app_engine, tid, JobRun)}
    assert by_id[old].status == "failed" and by_id[old].error_class == "Abandoned"
    assert by_id[old].finished_at is not None
    assert by_id[recent].status == "running" and by_id[new].status == "running"
    assert by_id[other].status == "running"  # another job is never touched


def test_finish_job_retries_once_after_a_dropped_connection(app_engine, tid, monkeypatch):
    job = telemetry.start_job(app_engine, tid, "sweep")
    real, calls = telemetry.tenant_session, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("server closed the connection")
        return real(*a, **k)

    monkeypatch.setattr(telemetry, "tenant_session", flaky)
    telemetry.finish_job(app_engine, tid, job, "ok", {"n": 1})
    monkeypatch.undo()
    assert [r.status for r in rows(app_engine, tid, JobRun)] == ["ok"]


def test_cancellation_marks_the_job_failed_and_propagates(app_engine, tid):
    def cancelled():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        telemetry.run_job(app_engine, tid, "j", cancelled)
    (r,) = rows(app_engine, tid, JobRun)
    assert r.status == "failed" and r.error_class == "KeyboardInterrupt"
