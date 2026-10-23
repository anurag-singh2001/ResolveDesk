"""Process-wide mock instances, so the API, executor and dev panel share one provider state."""

import uuid
from dataclasses import asdict

from mocks.base import Chaos
from mocks.messaging import MockMessaging
from mocks.payment import MockPayment
from mocks.sources import MockDeliveryApp, MockPOS

_MOCKS = {
    "payment": MockPayment(),
    "messaging": MockMessaging(),
    "pos": MockPOS(),
    "delivery_app": MockDeliveryApp(),
}


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
