"""Structured error log (S9.4): a logging handler that counts application errors.

What is stored, per (service, level, event code, exception class, day): a count and two
timestamps. The event code is the LOGGER NAME (set by our code, e.g. `app.engine.sweeper`) and
the class is the exception's class name. The log message and its arguments are never read, so a
customer's text, phone, name or token cannot reach the table by any route (they can only come
from a message, which this handler ignores). No tenant, no request or customer id either.

Failure safety: `emit` swallows every exception. A log call never raises into a request.
Rate limiting: the first occurrence of an error is written at once; further ones are counted in
memory and written as one batched increment at most every `flush_seconds`. The number of
distinct keys per day is capped, so a storm of new error types lands in one 'overflow' row
rather than filling the table.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, text

OWN_LOGGER = __name__
MAX_KEYS_PER_DAY = 200
OVERFLOW_CODE = "overflow"

_UPSERT = text(
    "INSERT INTO error_logs (service, level, event_code, error_class, day, occurrences, "
    "first_at, last_at) VALUES (:service, :level, :code, :cls, :day, :n, :at, :at) "
    "ON CONFLICT (service, level, event_code, error_class, day) DO UPDATE SET "
    "occurrences = error_logs.occurrences + EXCLUDED.occurrences, last_at = EXCLUDED.last_at"
)

Key = tuple[str, str, str, str, object]  # service, level, code, class, day


def service_of(logger_name: str) -> str:
    parts = logger_name.split(".")
    if parts[0] == "uvicorn":
        return "api"
    return (parts[1] if parts[0] == "app" and len(parts) > 1 else parts[0])[:40]


class ErrorLogHandler(logging.Handler):
    def __init__(
        self,
        engine: Engine,
        flush_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        level: int = logging.ERROR,
    ) -> None:
        super().__init__(level)
        self.engine, self.flush_seconds, self.clock = engine, flush_seconds, clock
        self._lock = threading.Lock()
        self._busy = threading.local()
        self._pending: dict[Key, int] = {}
        self._last_write: dict[Key, float] = {}
        self._day: object = None
        self._seen: set[Key] = set()

    def _key(self, record: logging.LogRecord, day) -> Key:
        exc = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
        level = (
            record.levelname if record.levelname in ("WARNING", "ERROR", "CRITICAL") else "ERROR"
        )
        key = (service_of(record.name), level, record.name[:80], exc[:80], day)
        if day != self._day:
            self._day, self._seen = day, set()
        if key not in self._seen:
            if len(self._seen) >= MAX_KEYS_PER_DAY:
                return (key[0], level, OVERFLOW_CODE, "", day)
            self._seen.add(key)
        return key

    def emit(self, record: logging.LogRecord) -> None:
        # Never raise, never recurse: our own warnings must not feed back into the handler.
        if record.name == OWN_LOGGER or getattr(self._busy, "on", False):
            return
        self._busy.on = True
        try:
            day = datetime.now(UTC).date()
            with self._lock:
                key = self._key(record, day)
                self._pending[key] = self._pending.get(key, 0) + 1
                now = self.clock()
                last = self._last_write.get(key)
                if last is not None and now - last < self.flush_seconds:
                    return
                self._last_write[key] = now  # also set on failure: no hammering a down database
                n = self._pending.pop(key)
            self._write(key, n)
        except Exception:  # noqa: S110
            pass
        finally:
            self._busy.on = False

    def _write(self, key: Key, n: int) -> None:
        service, level, code, cls, day = key
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    _UPSERT,
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

    def flush_pending(self) -> None:
        """Write what rate limiting is holding back (shutdown). Best effort."""
        try:
            with self._lock:
                items, self._pending = list(self._pending.items()), {}
            for key, n in items:
                self._write(key, n)
        except Exception:  # noqa: S110
            pass


def install_error_log_handler(
    engine: Engine, flush_seconds: float = 10.0, names: tuple[str, ...] = ("app", "uvicorn.error")
) -> Callable[[], None]:
    """Attach the handler to our loggers; returns an uninstall function (also flushes)."""
    handler = ErrorLogHandler(engine, flush_seconds)
    loggers = [logging.getLogger(n) for n in names]
    for lg in loggers:
        lg.addHandler(handler)

    def uninstall() -> None:
        for lg in loggers:
            lg.removeHandler(handler)
        handler.flush_pending()

    return uninstall
