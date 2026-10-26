"""Process-wide mock instances, so the API, executor and dev panel share one provider state."""

import uuid
from dataclasses import asdict

from mocks.base import Chaos, IdempotentMock
from mocks.messaging import MockMessaging
from mocks.payment import MockPayment
from mocks.persist import MockStateStore
from mocks.sources import MockDeliveryApp, MockPOS
from mocks.vouchers import MockVouchers

_MOCKS = {
    "payment": MockPayment(),
    "messaging": MockMessaging(),
    "pos": MockPOS(),
    "delivery_app": MockDeliveryApp(),
    "vouchers": MockVouchers(),
}


_STORE: MockStateStore | None = None


def enable_persistence(path: str) -> MockStateStore:
    """Keep the idempotent mocks' records in a JSON file (MOCK_STATE_FILE): load it now, write
    it (coalesced, ~200 ms) after changes. Chaos is never saved. Off by default (pure in-memory)."""
    global _STORE
    mocks = {name: m for name, m in _MOCKS.items() if isinstance(m, IdempotentMock)}
    store = MockStateStore(path, mocks)
    store.load()
    for mock in mocks.values():
        mock.attach_store(store)
    _STORE = store
    return store


def disable_persistence() -> None:
    global _STORE
    if _STORE is not None:
        _STORE.close()
    for mock in _MOCKS.values():
        if isinstance(mock, IdempotentMock):
            mock.attach_store(None)
    _STORE = None


def merchant_id_for(tenant_id: uuid.UUID) -> str:
    """The tenant's account at every mock provider (connectors use the same mapping)."""
    return f"m_{tenant_id.hex}"


def get_mock(name: str):
    return _MOCKS[name]


def mock_names() -> list[str]:
    return sorted(_MOCKS)


def set_chaos(name: str, chaos: Chaos, merchant_id: str | None = None) -> None:
    """merchant_id=None sets the default for every merchant (tests); the dev API always passes
    the caller's own merchant."""
    _MOCKS[name].chaos.set(chaos, merchant_id)


def chaos_state(merchant_id: str | None = None) -> dict[str, dict]:
    return {name: asdict(mock.chaos.get(merchant_id)) for name, mock in sorted(_MOCKS.items())}


def reset_mocks() -> None:
    """Clear all provider state and chaos (tests, dev panel reseed)."""
    for mock in _MOCKS.values():
        mock.reset()
