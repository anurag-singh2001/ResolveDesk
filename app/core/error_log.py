"""Structured error log (S9.4): a logging handler that counts application errors.

What is stored, per (service, level, event code, exception class, day): a count and two
timestamps. The event code is the LOGGER NAME (set by our code, e.g. `app.engine.sweeper`) and
the class is the exception's class name; both must look like identifiers or they are stored as
'unknown'. The log message and its arguments are never read, so a customer's text, phone, name
or token cannot reach the table by any route. No tenant, no request or customer id either.

The calling thread never touches the database (hard rule 5, and no pool starvation in an error
storm): `emit` only builds a small key and puts it on a bounded queue (a full queue drops the
event and counts the drop). One daemon thread drains the queue, adds the counts up and writes
them, at most once per `flush_seconds`, through a dedicated one-connection engine with short
timeouts. The number of distinct keys per day is capped, so a storm of new error types lands in
one 'overflow' row. `emit` swallows every exception: a log call never raises into a request.
Writes go through the SECURITY DEFINER function `log_error_count` (the app role has no table
grant, so tenant request code cannot read the log).
"""

import contextlib
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, text

OWN_LOGGER = __name__
MAX_KEYS_PER_DAY = 200
QUEUE_SIZE = 1000
OVERFLOW_CODE = "overflow"
DROPPED_CODE = "dropped"
UNKNOWN = "unknown"
_CODE = re.compile(r"^(app|uvicorn)[a-z0-9_.]*$")
_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_WRITE = text("SELECT log_error_count(:service, :level, :code, :cls, :day, :n, :at)")

Key = tuple[str, str, str, str, object]  # service, level, code, class, day


def service_of(logger_name: str) -> str:
    parts = logger_name.split(".")
    if parts[0] == "uvicorn":
        return "api"
    return (parts[1] if parts[0] == "app" and len(parts) > 1 else parts[0])[:40]


def _code_of(name: str) -> str:
    return name[:80] if _CODE.match(name) else UNKNOWN


def _class_of(record: logging.LogRecord) -> str:
    if not (record.exc_info and record.exc_info[0]):
        return ""
    name = record.exc_info[0].__name__
    return name[:80] if _CLASS.match(name) else UNKNOWN


class ErrorLogHandler(logging.Handler):
    def __init__(
        self,
        engine: Engine,
        flush_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        level: int = logging.ERROR,
        queue_size: int = QUEUE_SIZE,
    ) -> None:
        super().__init__(level)
        self.engine, self.flush_seconds, self.clock = engine, flush_seconds, clock
        self._queue: queue.Queue[Key] = queue.Queue(maxsize=queue_size)
        self.dropped = 0
        # Touched only by whoever drains (the daemon thread, or a test / shutdown, never both):
        self._pending: dict[Key, int] = {}
        self._seen: set[Key] = set()
        self._day: object = None
        self._last_flush = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- the calling thread: no database, no waiting ----------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name == OWN_LOGGER:  # our own warnings must not feed back
                return
            level = (
                record.levelname
                if record.levelname in ("WARNING", "ERROR", "CRITICAL")
                else "ERROR"
            )
            key = (
                service_of(record.name),
                level,
                _code_of(record.name),
                _class_of(record),
                datetime.now(UTC).date(),
            )
            try:
                self._queue.put_nowait(key)
            except queue.Full:
                self.dropped += 1
        except Exception:  # noqa: S110
            pass

    # -- the drain side ----------------------------------------------------------------------

    def _capped(self, key: Key) -> Key:
        day = key[4]
        if day != self._day:  # a new day: fresh key budget
            self._day, self._seen = day, set()
        if key in self._seen:
            return key
        if len(self._seen) >= MAX_KEYS_PER_DAY:
            return (key[0], key[1], OVERFLOW_CODE, "", day)
        self._seen.add(key)
        return key

    def process(self, force: bool = False) -> None:
        """Move queued events into the pending counts; write them if the interval has passed
        (or `force`). Runs on the drain thread (or a test); never on a request thread."""
        try:
            while True:
                key = self._capped(self._queue.get_nowait())
                self._pending[key] = self._pending.get(key, 0) + 1
        except queue.Empty:
            pass
        except Exception:  # noqa: S110
            pass
        if force or self.clock() - self._last_flush >= self.flush_seconds:
            self._flush()

    def _flush(self) -> None:
        self._last_flush = self.clock()  # also after a failure: no hammering a down database
        dropped, self.dropped = self.dropped, 0
        if dropped:
            day = datetime.now(UTC).date()
            key = ("error_log", "ERROR", DROPPED_CODE, "", day)
            self._pending[key] = self._pending.get(key, 0) + dropped
        items, self._pending = list(self._pending.items()), {}
        for key, n in items:
            self._write(key, n)

    def _write(self, key: Key, n: int) -> None:
        service, level, code, cls, day = key
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    _WRITE,
                    {
                        "service": service,
                        "level": level,
                        "code": code,
                        "cls": cls,
                        "day": day,
                        "n": n,
                        "at": datetime.now(UTC),
                    },
                )
        except Exception as exc:
            logging.getLogger(OWN_LOGGER).warning(
                "could not write error log: %s", type(exc).__name__
            )

    def _run(self) -> None:
        while not self._stop.wait(min(1.0, max(self.flush_seconds, 0.05))):
            with contextlib.suppress(Exception):  # the drain thread must outlive any one error
                self.process()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="error-log", daemon=True)
        self._thread.start()

    def flush_pending(self) -> None:
        """Shutdown: stop the thread, then write everything still held. Best effort."""
        try:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=3)
            self.process(force=True)
        except Exception:  # noqa: S110
            pass


def install_error_log_handler(
    engine: Engine,
    flush_seconds: float = 10.0,
    names: tuple[str, ...] = ("app", "uvicorn.error"),
    dedicated: bool = True,
) -> Callable[[], None]:
    """Attach the handler to our loggers and start its drain thread; returns an uninstall
    function (which also flushes). `dedicated` gives the thread its own one-connection engine
    with short timeouts, so the log can never take a connection the API needs."""
    if dedicated:
        engine = create_engine(
            engine.url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=2,
            pool_pre_ping=True,
            pool_recycle=120,
            connect_args={"connect_timeout": 3},
        )
    handler = ErrorLogHandler(engine, flush_seconds)
    handler.start()
    loggers = [logging.getLogger(n) for n in names]
    for lg in loggers:
        lg.addHandler(handler)

    def uninstall() -> None:
        for lg in loggers:
            lg.removeHandler(handler)
        handler.flush_pending()
        if dedicated:
            engine.dispose()

    return uninstall
