import pytest

from mocks.base import Chaos, IdempotencyConflict, ProviderTimeout
from mocks.messaging import MessageRequest, MockMessaging
from mocks.sources import MockDeliveryApp, MockPOS, ProviderError


@pytest.fixture
def merchant(tenant) -> str:
    return f"m_{tenant.name}"


def msg(text="Your refund is being processed"):
    return MessageRequest(to="+919800000000", template="status_update", params=(("text", text),))


def test_send_is_idempotent_and_outbox_has_one_message(merchant):
    m = MockMessaging()
    first = m.send(merchant, "case-1:status:1", msg())
    assert m.send(merchant, "case-1:status:1", msg()) == first
    assert m.outbox(merchant) == [msg()]


def test_send_same_key_other_payload_is_409(merchant):
    m = MockMessaging()
    m.send(merchant, "case-1:status:1", msg("a"))
    with pytest.raises(IdempotencyConflict):
        m.send(merchant, "case-1:status:1", msg("b"))


def test_accept_then_timeout_send_is_reconcilable(merchant):
    m = MockMessaging(Chaos(accept_then_timeout_rate=1.0))
    with pytest.raises(ProviderTimeout):
        m.send(merchant, "k", msg())
    assert m.get_message(merchant, "k").status == "succeeded"
    assert len(m.outbox(merchant)) == 1


@pytest.mark.parametrize("source_cls", [MockPOS, MockDeliveryApp])
def test_source_returns_stored_record_copy(merchant, source_cls):
    src = source_cls()
    src.put(merchant, "O1", {"total": 34900, "delivery_status": "delivered"})
    record = src.get_order(merchant, "O1")
    record["total"] = 1  # callers can't mutate provider state
    assert src.get_order(merchant, "O1")["total"] == 34900
    assert src.get_order(merchant, "missing") is None
    assert src.get_order(f"{merchant}_other", "O1") is None


@pytest.mark.parametrize(
    "chaos,error",
    [(Chaos(timeout_rate=1.0), ProviderTimeout), (Chaos(error_rate=1.0), ProviderError)],
)
def test_source_failure_injection(merchant, chaos, error):
    src = MockPOS(chaos)
    with pytest.raises(error):
        src.get_order(merchant, "O1")


def test_delivery_status(merchant):
    app = MockDeliveryApp()
    app.put(merchant, "O1", {"delivery_status": "out_for_delivery"})
    assert app.get_delivery_status(merchant, "O1") == "out_for_delivery"
