"""Optional on-disk state for the idempotent mocks, so provider records survive an API restart.

Off unless MOCK_STATE_FILE is set (tests and plain runs stay purely in memory). One JSON file
holds every mock's operations and in-flight requests. Chaos settings are NOT stored: they are
dev-panel toggles, and a restart should come back healthy.

Writes are atomic (temp file in the same directory, then os.replace) and serialised by a lock,
so a crash mid-write leaves the previous complete file, never a half-written one.
"""

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

VERSION = 1


class MockStateStore:
    def __init__(self, path: str | Path, mocks: dict[str, Any]) -> None:
        self.path = Path(path)
        self._mocks = mocks
        self._lock = threading.Lock()

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
