"""Mock source systems (POS, delivery app): read-only order lookups with failure injection.

Each speaks its own record shape; connectors (E2.3a) translate them into canonical models.
"""

import random
import threading
import time
from typing import Any

from mocks.base import Chaos, ProviderTimeout


class ProviderError(Exception):
    """Source system answered with an error (5xx)."""


class MockSource:
    def __init__(self, chaos: Chaos | None = None) -> None:
        self._lock = threading.Lock()
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self.set_chaos(chaos or Chaos())

    def set_chaos(self, chaos: Chaos) -> None:
        with self._lock:
            self.chaos = chaos
            self._rng = random.Random(chaos.seed)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._rng = random.Random(self.chaos.seed)

    def put(self, merchant_id: str, ref: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._records[(merchant_id, ref)] = dict(record)

    def _get(self, merchant_id: str, ref: str) -> dict[str, Any] | None:
        if self.chaos.delay_ms:
            time.sleep(self.chaos.delay_ms / 1000)
        with self._lock:
            if self.chaos.timeout_rate and self._rng.random() < self.chaos.timeout_rate:
                raise ProviderTimeout("source system timed out")
            if self.chaos.error_rate and self._rng.random() < self.chaos.error_rate:
                raise ProviderError("source system error")
            record = self._records.get((merchant_id, ref))
            return None if record is None else dict(record)  # callers can't mutate the store


class MockPOS(MockSource):
    def get_order(self, merchant_id: str, order_ref: str) -> dict[str, Any] | None:
        return self._get(merchant_id, order_ref)


class MockDeliveryApp(MockSource):
    def get_order(self, merchant_id: str, order_ref: str) -> dict[str, Any] | None:
        return self._get(merchant_id, order_ref)

    def get_delivery_status(self, merchant_id: str, order_ref: str) -> str | None:
        record = self._get(merchant_id, order_ref)
        return None if record is None else record.get("delivery_status")
