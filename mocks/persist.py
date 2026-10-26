"""Optional on-disk state for the idempotent mocks, so provider records survive an API restart.

Off unless MOCK_STATE_FILE is set (tests and plain runs stay purely in memory). One JSON file
holds every mock's operations and in-flight requests. Chaos settings are NOT stored: they are
dev-panel toggles, and a restart should come back healthy.

Writes are atomic (temp file in the same directory, then os.replace) and serialised by a lock,
so a crash mid-write leaves the previous complete file, never a half-written one.

Writes are also coalesced: a mutation only marks the store dirty, and a background timer writes
at most once per FLUSH_INTERVAL_S (rewriting the whole file after every mutation made a long
campaign quadratic). reset and process exit flush at once. Trade-off: a hard crash can lose the
last ~200 ms of mock records (docs/DECISIONS.md).
"""

import atexit
import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

VERSION = 1
FLUSH_INTERVAL_S = 0.2

log = logging.getLogger(__name__)


class MockStateStore:
    def __init__(self, path: str | Path, mocks: dict[str, Any]) -> None:
        self.path = Path(path)
        self._mocks = mocks
        self._lock = threading.Lock()
        self._meta = threading.Lock()  # guards _dirty and _timer; never held while writing
        self._flush_lock = threading.Lock()  # one flush at a time
        self._dirty = False
        self._timer: threading.Timer | None = None
        self._closed = False  # after close() nothing arms a timer or writes again
        atexit.register(self.flush)

    def load(self) -> None:
        """Fill the mocks from the file. Missing file = fresh start; an unreadable one is an
        error, because quietly forgetting provider records is the bug this exists to prevent."""
        with self._lock:
            if not self.path.exists():
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") != VERSION:
                    raise ValueError(f"unsupported version {data.get('version')!r}")
                for name, mock in self._mocks.items():
                    mock.load_state(data.get("mocks", {}).get(name, {}))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise RuntimeError(
                    f"cannot read mock state file {self.path} ({exc}); fix or delete it"
                ) from exc

    def request_save(self) -> None:
        """Mark the state changed; a timer writes it within FLUSH_INTERVAL_S. Cheap, so mocks
        can call it after every mutation."""
        with self._meta:
            if self._closed:
                return
            self._dirty = True
            if self._timer is None:
                self._timer = threading.Timer(FLUSH_INTERVAL_S, self._timer_fired)
                self._timer.daemon = True
                self._timer.start()

    def _timer_fired(self) -> None:
        with self._meta:
            self._timer = None
        try:
            self.flush()
        except Exception:  # noqa: BLE001 - the timer thread must not die; retry next change
            log.exception("mock state flush failed")
            with self._meta:
                self._dirty = True

    def flush(self) -> None:
        """Write now if anything changed since the last write (reset, exit and tests)."""
        with self._flush_lock:
            with self._meta:
                dirty, self._dirty = self._dirty, False
                timer, self._timer = self._timer, None
            if timer is not None:
                timer.cancel()
            if dirty:
                try:
                    self.save()
                except BaseException:
                    with self._meta:
                        self._dirty = True
                    raise

    def close(self) -> None:
        """Final write, then stop: cancel the timer and drop the exit hook, so a store that is
        no longer used (persistence disabled, a test finished) can never write again."""
        self.flush()
        with self._meta:
            self._closed = True
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        atexit.unregister(self.flush)

    def save(self) -> None:
        with self._lock:  # snapshots are taken inside, so the last writer holds the newest state
            payload = {
                "version": VERSION,
                "mocks": {name: mock.dump_state() for name, mock in self._mocks.items()},
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, sort_keys=True)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
