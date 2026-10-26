"""MOCK_STATE_FILE: mock providers keep their records across a restart (a second instance)."""

import json

import pytest

from mocks import registry
from mocks.base import Chaos, IdempotencyConflict
from mocks.messaging import MessageRequest, MockMessaging
from mocks.payment import MockPayment, RefundRequest
from mocks.persist import MockStateStore
from mocks.vouchers import MockVouchers, VoucherRequest

MERCHANT = "m_test"


def _registry(path):
    """What a freshly started API process builds: new mocks, loaded from the file."""
    mocks = {"payment": MockPayment(), "messaging": MockMessaging(), "vouchers": MockVouchers()}
    store = MockStateStore(path, mocks)
    store.load()
    for mock in mocks.values():
        mock.attach_store(store)
    return mocks


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "nested" / "mock_state.json"


def test_a_second_instance_sees_the_refund_by_idempotency_key(state_file):
    first = _registry(state_file)
    req = RefundRequest("pay_1", 12_500, reason="missing item")
    made = first["payment"].refund(MERCHANT, "key-1", req)

    second = _registry(state_file)
    seen = second["payment"].get_refund(MERCHANT, "key-1")
    assert seen == made and seen.status == "succeeded" and seen.amount_paise == 12_500
    assert second["payment"].get_refund(MERCHANT, "never-sent") is None


def test_idempotency_still_holds_after_reload(state_file):
    req = RefundRequest("pay_1", 12_500)
    first = _registry(state_file)["payment"].refund(MERCHANT, "key-1", req)

    second = _registry(state_file)["payment"]
    again = second.refund(MERCHANT, "key-1", req)
    assert again.operation_id == first.operation_id
    assert len(second.operations(MERCHANT)) == 1  # same key twice: one operation
    assert second.operations(MERCHANT)[0].attempts == 2
    with pytest.raises(IdempotencyConflict):
        second.refund(MERCHANT, "key-1", RefundRequest("pay_1", 99))
    # A new key after reload gets a fresh, distinct operation id.
    other = second.refund(MERCHANT, "key-2", req)
    assert other.operation_id != first.operation_id


def test_vouchers_and_messaging_outbox_survive(state_file):
    first = _registry(state_file)
    voucher = first["vouchers"].issue(MERCHANT, "v-1", VoucherRequest("cust", 5_000, "ord-1"))
    msg = MessageRequest("+911234567890", "campaign", (("offer", "10%"), ("name", "Asha")))
    first["messaging"].send(MERCHANT, "m-1", msg)

    second = _registry(state_file)
    assert second["vouchers"].get_voucher(MERCHANT, "v-1") == voucher
    assert second["messaging"].outbox(MERCHANT) == [msg]  # request rebuilt with tuple params
    second["messaging"].send(MERCHANT, "m-1", msg)  # same key: still one message
    assert len(second["messaging"].outbox(MERCHANT)) == 1


def test_processing_state_and_in_flight_requests_are_kept(state_file):
    first = _registry(state_file)
    first["payment"].set_chaos(Chaos(processing_rate=1.0, settle_after_polls=3), MERCHANT)
    first["payment"].refund(MERCHANT, "slow", RefundRequest("pay_1", 100))
    first["payment"].get_refund(MERCHANT, "slow")  # one poll, persisted

    second = _registry(state_file)["payment"]
    assert second.chaos.get(MERCHANT) == Chaos()  # chaos is not persisted
    assert second.get_refund(MERCHANT, "slow").status == "processing"  # 2 -> 1 polls left
    assert second.get_refund(MERCHANT, "slow").status == "succeeded"


def test_file_is_complete_json_and_leaves_no_temp_files(state_file):
    first = _registry(state_file)
    first["payment"].refund(MERCHANT, "k", RefundRequest("pay_1", 100))
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["version"] == 1 and len(data["mocks"]["payment"]["ops"]) == 1
    assert [p.name for p in state_file.parent.iterdir()] == [state_file.name]


def test_unreadable_file_fails_loudly(state_file):
    state_file.parent.mkdir(parents=True)
    state_file.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="mock state file"):
        _registry(state_file)


def test_reset_mocks_clears_the_configured_file(state_file):
    registry.enable_persistence(str(state_file))
    try:
        registry.get_mock("payment").refund(MERCHANT, "k", RefundRequest("pay_1", 100))
        assert json.loads(state_file.read_text())["mocks"]["payment"]["ops"]
        registry.reset_mocks()
        data = json.loads(state_file.read_text())
        assert all(not m["ops"] and not m["inflight"] for m in data["mocks"].values())
        assert registry.get_mock("payment").get_refund(MERCHANT, "k") is None
    finally:
        registry.disable_persistence()
        registry.reset_mocks()


def test_without_a_state_file_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock = MockPayment()
    mock.refund(MERCHANT, "k", RefundRequest("pay_1", 100))
    assert list(tmp_path.iterdir()) == []
