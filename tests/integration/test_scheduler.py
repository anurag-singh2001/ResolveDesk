"""In-app job scheduler (S9.3), for every tenant: due times from a fake clock (no real sleeps),
no overlap, one runner across processes (advisory lock), failures recorded and survived, clean
shutdown, retention a dry run unless told otherwise, off by default."""

import asyncio
import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

import app.main as main_module
from app.config import Settings
from app.core.db import tenant_session
from app.core.models import JobRun, PlatformJobRun
from app.core.scheduler import ScheduledJob, Scheduler, job_lock
from app.core.telemetry import start_job
from app.core.tenancy import tenant_id_for
from app.engine import scheduled_jobs

SECRET = "refund me 9876543210 at 12 Hidden Lane"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@contextmanager
def always(engine, name):
    yield True


@pytest.fixture
def tid(seeded, tenant, maint_engine, owner_engine):
    tid = tenant_id_for(seeded[tenant.name].slug)

    def clean():
        with tenant_session(tid, maint_engine) as s:
            s.execute(delete(JobRun).where(JobRun.tenant_id == tid))
        with owner_engine.begin() as c:
            c.execute(text("DELETE FROM platform_job_runs"))
            c.execute(text("DELETE FROM job_leases"))

    clean()
    yield tid
    clean()


def job_rows(engine, tid, job=None):
    with tenant_session(tid, engine) as s:
        q = select(JobRun.job, JobRun.status, JobRun.error_class).where(JobRun.tenant_id == tid)
        if job:
            q = q.where(JobRun.job == job)
        return [tuple(r) for r in s.execute(q)]


def platform_rows(engine, job=None):
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        q = select(PlatformJobRun.job, PlatformJobRun.status, PlatformJobRun.error_class)
        if job:
            q = q.where(PlatformJobRun.job == job)
        return [tuple(r) for r in s.execute(q)]


def make(engine, jobs, clock, lock=always, **kw):
    s = Scheduler(engine, jobs, clock=clock, startup_delay=10, lock=lock, **kw)
    s.schedule_first_runs()
    return s


# --- due times, off switches ----------------------------------------------------------


def test_due_times_follow_the_fake_clock_and_catch_up_runs_once(app_engine):
    clock, ran = Clock(), []
    s = make(app_engine, [ScheduledJob("j", 100, lambda: ran.append(clock()))], clock)

    async def go():
        await s.tick()
        await s.wait_idle()
        assert ran == []  # first run is startup_delay (10 s) after start
        clock.t += 10
        await s.tick()
        await s.wait_idle()
        assert len(ran) == 1
        clock.t += 99  # not yet
        await s.tick()
        await s.wait_idle()
        assert len(ran) == 1
        clock.t += 100 * 50  # the host slept through fifty intervals
        await s.tick()
        await s.wait_idle()
        assert len(ran) == 2  # ONE catch-up run, not fifty
        await s.tick()
        await s.wait_idle()
        assert len(ran) == 2

    asyncio.run(go())


def test_a_job_with_interval_zero_is_off(app_engine):
    ran = []
    s = make(app_engine, [ScheduledJob("j", 0, lambda: ran.append(1))], Clock())
    assert s.jobs == []


def test_scheduler_is_off_by_default_and_the_app_starts_no_loop(monkeypatch):
    assert Settings(_env_file=None).scheduler_enabled is False

    def boom(*a, **k):
        raise AssertionError("scheduler must not be built when disabled")

    monkeypatch.setattr("app.core.scheduler.Scheduler.__init__", boom)
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(_env_file=None))
    with TestClient(main_module.create_app()) as c:
        assert c.get("/health").json() == {"status": "ok"}


def test_enabled_app_starts_the_scheduler_and_stops_it_cleanly(monkeypatch):
    calls = []

    class Fake:
        jobs = []

        def __init__(self, *a, **k):
            calls.append("init")

        def start(self):
            calls.append("start")

        async def stop(self):
            calls.append("stop")

    monkeypatch.setattr(
        main_module, "get_settings", lambda: Settings(_env_file=None, scheduler_enabled=True)
    )
    monkeypatch.setattr("app.core.scheduler.Scheduler", Fake)
    monkeypatch.setattr("app.core.db.get_engine", lambda: object())
    monkeypatch.setattr("app.engine.scheduled_jobs.build_jobs", lambda s, e: [])
    with TestClient(main_module.create_app()) as c:
        assert c.get("/health").status_code == 200
        assert calls == ["init", "start"]
    assert calls == ["init", "start", "stop"]


# --- overlap, failure, lock -----------------------------------------------------------


def test_overlapping_tick_is_skipped_and_recorded(app_engine, tid):
    clock, gate, started, runs = Clock(), threading.Event(), threading.Event(), []

    def slow():
        runs.append(1)
        started.set()
        gate.wait(10)

    s = make(app_engine, [ScheduledJob("slow", 100, slow, lambda: [tid])], clock)

    async def go():
        clock.t += 10
        await s.tick()
        assert await asyncio.to_thread(started.wait, 10)
        clock.t += 100  # next tick while the first run is still going
        await s.tick()
        gate.set()
        await s.wait_idle()

    asyncio.run(go())
    assert len(runs) == 1
    assert job_rows(app_engine, tid, "slow") == [("slow", "skipped", None)]


def test_a_failing_job_is_recorded_without_its_message_and_the_loop_goes_on(app_engine, tid):
    clock, n = Clock(), []

    def bad():
        n.append(1)
        raise RuntimeError(SECRET)

    s = make(app_engine, [ScheduledJob("bad_job", 100, bad)], clock)

    async def go():
        for _ in range(2):
            clock.t += 100
            await s.tick()
            await s.wait_idle()

    asyncio.run(go())
    assert len(n) == 2  # it kept being scheduled
    assert platform_rows(app_engine, "bad_job") == [("bad_job", "failed", "RuntimeError")] * 2
    with tenant_session(tid, app_engine) as se:
        assert SECRET not in str(se.execute(select(JobRun)).all())


def test_one_runner_per_job_across_processes(app_engine, tid):
    with job_lock(app_engine, "same") as mine:
        assert mine is True
        with job_lock(app_engine, "same") as other:  # a second app instance
            assert other is False
        with job_lock(app_engine, "different") as unrelated:
            assert unrelated is True
    with job_lock(app_engine, "same") as again:  # released when the runner is done
        assert again is True


def test_no_transaction_stays_open_while_a_job_holds_the_lease(app_engine, tid):
    with job_lock(app_engine, "quiet") as got:
        assert got
        with app_engine.connect() as c:  # the lease is committed: visible from elsewhere
            assert (
                c.execute(text("SELECT count(*) FROM job_leases WHERE job = 'quiet'")).scalar() == 1
            )


def test_a_stale_lease_is_taken_over(app_engine, tid, owner_engine):
    with owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO job_leases (job, holder, expires_at) "
                "VALUES ('dead', gen_random_uuid(), now() - interval '1 minute')"
            )
        )
    with job_lock(app_engine, "dead") as got:  # the holder died: its lease ran out
        assert got is True
    with owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO job_leases (job, holder, expires_at) "
                "VALUES ('alive', gen_random_uuid(), now() + interval '1 minute')"
            )
        )
    with job_lock(app_engine, "alive") as got:  # a live lease is respected
        assert got is False


def test_the_lease_is_released_when_the_job_fails(app_engine, tid):
    with pytest.raises(RuntimeError), job_lock(app_engine, "boom") as got:
        assert got
        raise RuntimeError("job failed")
    with job_lock(app_engine, "boom") as again:
        assert again is True


def test_the_heartbeat_keeps_a_long_job_leased(app_engine, tid):
    import time

    with job_lock(app_engine, "long", ttl=0.6) as got:  # beats every 0.2 s
        assert got
        time.sleep(1.5)  # well past the ttl
        with job_lock(app_engine, "long", ttl=0.6) as other:
            assert other is False


def test_a_second_instance_skips_while_the_first_holds_the_lock(app_engine, tid):
    clock, ran = Clock(), []
    s = make(
        app_engine,
        [ScheduledJob("held", 100, lambda: ran.append(1), lambda: [tid])],
        clock,
        lock=job_lock,
    )

    async def go():
        clock.t += 10
        await s.tick()
        await s.wait_idle()

    with job_lock(app_engine, "held") as first:
        assert first
        asyncio.run(go())
    assert ran == []
    assert job_rows(app_engine, tid, "held") == [("held", "skipped", None)]


# --- the real jobs --------------------------------------------------------------------


def test_real_jobs_run_and_are_recorded_per_tenant(app_engine, tid):
    settings = Settings(
        _env_file=None,
        app_env="test",
        scheduler_sweep_interval_seconds=100,
        scheduler_retention_interval_seconds=100,
        scheduler_growth_interval_seconds=100,
    )
    clock = Clock()
    s = make(app_engine, scheduled_jobs.build_jobs(settings, app_engine), clock, lock=job_lock)

    async def go():
        clock.t += 10
        await s.tick()
        await s.wait_idle()

    asyncio.run(go())
    assert {(j, st) for j, st, _ in job_rows(app_engine, tid)} == {
        ("sweep", "ok"),
        ("retention_dry_run", "ok"),
        ("growth_nightly", "ok"),
    }
    assert platform_rows(app_engine) == []  # nothing failed, so nothing platform-level


@pytest.mark.parametrize("apply", [False, True])
def test_retention_is_a_dry_run_unless_the_setting_says_otherwise(monkeypatch, apply):
    seen = []
    monkeypatch.setattr(scheduled_jobs, "purge_all", lambda engine, apply=False: seen.append(apply))
    settings = Settings(_env_file=None, scheduler_retention_apply=apply)
    (job,) = [
        j for j in scheduled_jobs.build_jobs(settings, None) if j.name.startswith("retention")
    ]
    job.run()
    assert seen == [apply]
    assert job.name == ("retention_apply" if apply else "retention_dry_run")
    assert Settings(_env_file=None).scheduler_retention_apply is False


# --- shutdown -------------------------------------------------------------------------


def test_shutdown_closes_a_job_that_will_not_finish(app_engine, tid):
    clock, gate, started = Clock(), threading.Event(), threading.Event()

    def stuck():
        start_job(app_engine, tid, "stuck")  # a row left 'running', as run_job would
        started.set()
        gate.wait(10)

    s = make(app_engine, [ScheduledJob("stuck", 100, stuck, lambda: [tid])], clock, grace=0.05)

    async def go():
        clock.t += 10
        await s.tick()
        assert await asyncio.to_thread(started.wait, 10)
        await s.stop()

    try:
        asyncio.run(go())
        assert job_rows(app_engine, tid, "stuck") == [("stuck", "failed", "Shutdown")]
    finally:
        gate.set()


def test_the_loop_runs_on_its_own_and_stops(app_engine):
    ran = threading.Event()
    s = Scheduler(
        app_engine,
        [ScheduledJob("loop_job", 1, ran.set)],
        tick_seconds=0.01,
        startup_delay=0,
        lock=always,
    )

    async def go():
        s.start()
        assert await asyncio.to_thread(ran.wait, 10)
        await s.stop()
        assert s._loop_task.done()

    asyncio.run(go())


def test_platform_job_runs_is_not_tenant_owned_and_the_app_role_cannot_delete(app_engine):
    with app_engine.connect() as c:
        cols = c.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
            {"t": "platform_job_runs"},
        ).scalars()
        cols = list(cols)
    assert cols and "tenant_id" not in cols
    with pytest.raises(DBAPIError), app_engine.begin() as c:
        c.execute(text("DELETE FROM platform_job_runs"))
    with pytest.raises(DBAPIError), app_engine.begin() as c:
        c.execute(text("SELECT * FROM platform_jobs_v"))  # only the platform role reads the view


def test_shutdown_closes_every_running_job_not_only_the_first(app_engine, tid):
    clock, gate = Clock(), threading.Event()
    started = {"a_job": threading.Event(), "b_job": threading.Event(), "c_job": threading.Event()}

    def stuck(name):
        def run():
            start_job(app_engine, tid, name)
            started[name].set()
            gate.wait(10)

        return run

    jobs = [ScheduledJob(n, 100, stuck(n), lambda: [tid]) for n in started]
    s = make(app_engine, jobs, clock, grace=0.05)

    async def go():
        clock.t += 10
        await s.tick()
        for ev in started.values():
            assert await asyncio.to_thread(ev.wait, 10)
        await s.stop()

    try:
        asyncio.run(go())
        assert {j: (st, e) for j, st, e in job_rows(app_engine, tid)} == {
            n: ("failed", "Shutdown") for n in started
        }
    finally:
        gate.set()


def test_skips_are_recorded_at_most_once_an_hour(app_engine, tid):
    clock, gate, started = Clock(), threading.Event(), threading.Event()

    def slow():
        started.set()
        gate.wait(10)

    s = make(app_engine, [ScheduledJob("noisy", 1, slow, lambda: [tid])], clock)

    async def go():
        clock.t += 10
        await s.tick()
        assert await asyncio.to_thread(started.wait, 10)
        for _ in range(5):  # five overlapping ticks within the hour
            clock.t += 2
            await s.tick()
        clock.t += 3600  # an hour later it is worth another row
        await s.tick()
        gate.set()
        await s.wait_idle()

    asyncio.run(go())
    assert job_rows(app_engine, tid, "noisy").count(("noisy", "skipped", None)) == 2


def test_the_platform_role_reads_the_job_view_and_not_the_tables(app_engine, owner_engine, tid):
    from sqlalchemy import create_engine, event

    from app.config import get_settings
    from app.core.db import ENGINE_OPTIONS
    from app.core.telemetry import finish_platform_job, start_platform_job

    finish_platform_job(app_engine, start_platform_job(app_engine, "view_job"), "failed", None, "X")
    engine = create_engine(get_settings().test_migration_database_url, **ENGINE_OPTIONS)

    @event.listens_for(engine, "connect")
    def _switch(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("SET ROLE resolvedesk_platform")
        cur.close()
        dbapi_conn.commit()

    try:
        with engine.connect() as c:
            rows = c.execute(text("SELECT job, status, runs FROM platform_jobs_v")).all()
        assert ("view_job", "failed", 1) in [tuple(r) for r in rows]
        for table in ("platform_job_runs", "job_leases"):
            with pytest.raises(DBAPIError), engine.connect() as c:
                c.execute(text(f"SELECT 1 FROM {table}"))
    finally:
        engine.dispose()
