"""In-app job scheduler (S9.3): one plain asyncio loop, no new dependency.

Every `tick` looks at the injected clock, starts each due job in a worker thread (so a slow job
never blocks the event loop or the API) and moves its next due time forward. Rules:

- No overlap: a job still running when its next tick arrives is skipped and recorded as such.
- One runner across app instances: a committed lease row in `job_leases` (holder, expiry),
  taken with one INSERT ... ON CONFLICT in a short transaction, renewed by a heartbeat thread
  while the job runs and deleted at the end. No transaction stays open during the job (hard
  rule 5) and nothing depends on a pooled connection staying alive. A lease whose holder died
  expires after `LEASE_TTL` and can be taken over. If a job outlives its lease (heartbeat
  starved, database unreachable) a second process can start it too: all jobs are idempotent.
- A job that raises is logged by class name and recorded; the loop and the API go on.
- Catch-up: due times are plain "last start + interval". After a sleep or stall the job runs
  ONCE at the next tick, never once per missed interval. A host that sleeps runs nothing while
  asleep; the first run after boot comes `startup_delay` seconds after start.
- Shutdown: the loop stops, running jobs get `grace` seconds, and any tenant job still marked
  'running' after that is closed as failed ("Shutdown").

Time is injected (`clock` returns seconds), so tests drive `tick()` with a fake clock.
"""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from app.core.telemetry import (
    close_running_jobs,
    finish_platform_job,
    record_tenant_skips,
    start_platform_job,
)

log = logging.getLogger(__name__)

LEASE_TTL = 120.0  # seconds a lease lives without a heartbeat
SKIP_RECORD_EVERY = 3600.0  # at most one 'skipped' row per job per hour

_TAKE = text(
    "INSERT INTO job_leases (job, holder, expires_at) "
    "VALUES (:job, :holder, now() + make_interval(secs => :ttl)) "
    "ON CONFLICT (job) DO UPDATE SET holder = EXCLUDED.holder, expires_at = EXCLUDED.expires_at "
    "WHERE job_leases.expires_at < now() RETURNING holder"
)
_RENEW = text(
    "UPDATE job_leases SET expires_at = now() + make_interval(secs => :ttl) "
    "WHERE job = :job AND holder = :holder"
)
_RELEASE = text("DELETE FROM job_leases WHERE job = :job AND holder = :holder")


def _short(engine: Engine, stmt, **params):
    with engine.begin() as conn:  # one short committed transaction
        result = conn.execute(stmt, params)
        return result.first() if result.returns_rows else None


@contextmanager
def job_lock(engine: Engine, name: str, ttl: float = LEASE_TTL) -> Iterator[bool]:
    """Try to become the one runner of `name`; yields whether we are. The lease is renewed
    every ttl/3 seconds while the block runs and released when it ends, however it ends."""
    holder = uuid.uuid4()
    got = _short(engine, _TAKE, job=name, holder=holder, ttl=ttl)
    if got is None or got[0] != holder:
        yield False
        return
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(ttl / 3):
            try:
                _short(engine, _RENEW, job=name, holder=holder, ttl=ttl)
            except Exception as exc:  # next beat may succeed; the lease may lapse meanwhile
                log.warning("could not renew lease for %s: %s", name, type(exc).__name__)

    heartbeat = threading.Thread(target=beat, name=f"lease-{name}", daemon=True)
    heartbeat.start()
    try:
        yield True
    finally:
        stop.set()
        heartbeat.join(timeout=5)
        try:
            _short(engine, _RELEASE, job=name, holder=holder)
        except Exception as exc:  # it will expire on its own
            log.warning("could not release lease for %s: %s", name, type(exc).__name__)


@dataclass
class ScheduledJob:
    name: str
    interval: float  # seconds; 0 or less = off
    run: Callable[[], None]  # blocking; runs in a worker thread
    tenant_ids: Callable[[], list[uuid.UUID]] | None = None  # None: a platform-level job
    next_due: float = field(default=0.0, init=False)
    running: bool = field(default=False, init=False)
    started_wall: datetime | None = field(default=None, init=False)


class Scheduler:
    def __init__(
        self,
        engine: Engine,
        jobs: list[ScheduledJob],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] = asyncio.sleep,
        tick_seconds: float = 30.0,
        startup_delay: float = 60.0,
        grace: float = 10.0,
        lock=job_lock,
    ) -> None:
        self.engine = engine
        self.jobs = [j for j in jobs if j.interval > 0]
        self.clock, self.sleep = clock, sleep
        self.tick_seconds, self.startup_delay, self.grace = tick_seconds, startup_delay, grace
        self._lock = lock
        self._tasks: set[asyncio.Task] = set()
        self._loop_task: asyncio.Task | None = None
        self._stopping = False
        self._last_skip: dict[str, float] = {}

    # -- the loop -------------------------------------------------------------------------

    def start(self) -> None:
        """Schedule the first runs and start the loop on the running event loop."""
        self.schedule_first_runs()
        self._loop_task = asyncio.get_running_loop().create_task(self._loop())

    def schedule_first_runs(self) -> None:
        now = self.clock()
        for job in self.jobs:
            job.next_due = now + self.startup_delay

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the loop must outlive any one bad tick
                log.warning("scheduler tick failed: %s", type(exc).__name__)
            await self.sleep(self.tick_seconds)

    async def tick(self) -> None:
        now = self.clock()
        for job in self.jobs:
            if now < job.next_due:
                continue
            job.next_due = now + job.interval  # from this start: no replay of missed intervals
            if job.running:
                await asyncio.to_thread(self._record_skip, job)
                continue
            job.running = True
            job.started_wall = datetime.now(UTC)
            task = asyncio.get_running_loop().create_task(self._run(job))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run(self, job: ScheduledJob) -> None:
        try:
            await asyncio.to_thread(self._execute, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("scheduled job %s failed: %s", job.name, type(exc).__name__)
        finally:
            job.running = False

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        self._stopping = True
        # Snapshot first: cancelling a task flips its job's `running` flag in its finally block.
        running = [(j, j.started_wall) for j in self.jobs if j.running]
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        pending = list(self._tasks)
        if pending:
            _, still = await asyncio.wait(pending, timeout=self.grace)
            for task in still:
                task.cancel()  # a thread cannot be killed; its rows are closed below
            for job, since in running:
                if job.tenant_ids is not None and since is not None:
                    await asyncio.to_thread(
                        close_running_jobs,
                        self.engine,
                        job.tenant_ids(),
                        job.name,
                        since,
                        "Shutdown",
                    )

    # -- the worker thread ------------------------------------------------------------------

    def _record_skip(self, job: ScheduledJob) -> None:
        """One 'skipped' row per job per hour at most: an overlap or a busy lease can repeat
        every tick, and the table should not fill with them."""
        now = self.clock()
        last = self._last_skip.get(job.name)
        if last is not None and now - last < SKIP_RECORD_EVERY:
            return
        self._last_skip[job.name] = now
        if job.tenant_ids is None:
            start_platform_job(self.engine, job.name, "skipped")
        else:
            record_tenant_skips(self.engine, job.tenant_ids(), job.name)

    def _execute(self, job: ScheduledJob) -> None:
        try:
            with self._lock(self.engine, job.name) as got:
                if not got:  # another app process is running this job
                    self._record_skip(job)
                    return
                job.run()
        except Exception as exc:
            # Tenant jobs record their own failures per tenant (run_job); this is whatever
            # escaped that: the lock, the tenant list, a platform job. Class name only.
            log.warning("scheduled job %s failed: %s", job.name, type(exc).__name__)
            job_id = start_platform_job(self.engine, job.name)
            finish_platform_job(self.engine, job_id, "failed", error_class=type(exc).__name__)
