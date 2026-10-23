"""Process-wide mock instances, so the API, executor and dev panel share one provider state."""

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


def get_mock(name: str):
    return _MOCKS[name]


def mock_names() -> list[str]:
    return sorted(_MOCKS)


def set_chaos(name: str, chaos: Chaos) -> None:
    _MOCKS[name].set_chaos(chaos)


def chaos_state() -> dict[str, dict]:
    return {name: asdict(mock.chaos) for name, mock in sorted(_MOCKS.items())}


def reset_mocks() -> None:
    """Clear all provider state and chaos (tests, dev panel reseed)."""
    for mock in _MOCKS.values():
        mock.set_chaos(Chaos())
        mock.reset()
