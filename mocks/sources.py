"""Mock source systems (POS, delivery app): read-only order lookups with failure injection.

Each speaks its own record shape; connectors (E2.3a) translate them into canonical models.
"""

import threading
import time
from typing import Any

from mocks.base import Chaos, ChaosByMerchant, ProviderTimeout, ProviderUnavailable, _hit


class ProviderError(Exception):
    """Source system answered with an error (5xx)."""


class MockSource:
    def __init__(self, chaos: Chaos | None = None) -> None:
        self._lock = threading.Lock()
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self.chaos = ChaosByMerchant()
        if chaos is not None:
            self.chaos.set(chaos)

    def set_chaos(self, chaos: Chaos, merchant_id: str | None = None) -> None:
        self.chaos.set(chaos, merchant_id)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
        self.chaos.reset()

    def put(self, merchant_id: str, ref: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._records[(merchant_id, ref)] = dict(record)

    def _get(self, merchant_id: str, ref: str) -> dict[str, Any] | None:
        chaos, rng = self.chaos.draw(merchant_id, ref)
        if chaos.delay_ms:
            time.sleep(chaos.delay_ms / 1000)
        if _hit(rng, chaos.timeout_rate):
            raise ProviderTimeout("source system timed out")
        if _hit(rng, chaos.transient_error_rate):
            raise ProviderUnavailable("source system temporarily unavailable")
        if _hit(rng, chaos.error_rate):
            raise ProviderError("source system error")
        with self._lock:
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
