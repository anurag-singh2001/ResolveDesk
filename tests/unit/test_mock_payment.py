"""Contract tests for the mock payment provider (PROJECT.md section 10)."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from mocks.base import Chaos, IdempotencyConflict, ProviderTimeout, payload_hash
from mocks.payment import MockPayment, RefundRequest

KEY = "P-1:refund:1"


@pytest.fixture
def merchant(tenant) -> str:
    """Provider-side merchant account; one per tenant."""
    return f"m_{tenant.name}"


def req(amount=34900, ref="PAY-1"):
    return RefundRequest(payment_reference=ref, amount_paise=amount)


def test_same_key_same_payload_is_the_same_operation(merchant):
    pay = MockPayment()
    first = pay.refund(merchant, KEY, req())
    again = pay.refund(merchant, KEY, req())
    assert again == first
    assert first.status == "succeeded"
    assert len(pay.operations(merchant)) == 1


def test_same_key_different_payload_is_409(merchant):
    pay = MockPayment()
    pay.refund(merchant, KEY, req(amount=34900))
    with pytest.raises(IdempotencyConflict) as exc:
        pay.refund(merchant, KEY, req(amount=34901))
    assert exc.value.http_status == 409
    assert len(pay.operations(merchant)) == 1


def test_keys_are_scoped_per_merchant(merchant):
    pay = MockPayment()
    pay.refund(merchant, KEY, req(amount=100))
    pay.refund(f"{merchant}_other", KEY, req(amount=200))  # same key, other merchant: fine
    assert len(pay.operations(merchant)) == 1


def test_timeout_before_accept_applies_nothing_and_retry_succeeds(merchant):
    pay = MockPayment(Chaos(timeout_rate=1.0))
    with pytest.raises(ProviderTimeout):
        pay.refund(merchant, KEY, req())
    assert pay.get_refund(merchant, KEY) is None
    pay.set_chaos(Chaos())
    assert pay.refund(merchant, KEY, req()).status == "succeeded"
    assert len(pay.operations(merchant)) == 1


def test_accept_then_timeout_is_found_by_reconciliation_and_never_duplicated(merchant):
    pay = MockPayment(Chaos(accept_then_timeout_rate=1.0))
    with pytest.raises(ProviderTimeout):
        pay.refund(merchant, KEY, req())
    found = pay.get_refund(merchant, KEY)  # reconcile by key before any retry
    assert found is not None and found.status == "succeeded"
    pay.set_chaos(Chaos())
    assert pay.refund(merchant, KEY, req()).operation_id == found.operation_id
    assert len(pay.operations(merchant)) == 1


def test_declined_refund_is_final_for_that_key(merchant):
    pay = MockPayment(Chaos(error_rate=1.0))
    first = pay.refund(merchant, KEY, req())
    pay.set_chaos(Chaos())
    assert first.status == "failed" and first.failure_reason
    assert pay.refund(merchant, KEY, req()) == first  # a retry with the same key never re-applies


def test_processing_settles_after_polls(merchant):
    pay = MockPayment(Chaos(processing_rate=1.0, settle_after_polls=2))
    assert pay.refund(merchant, KEY, req()).status == "processing"
    assert pay.get_refund(merchant, KEY).status == "processing"
    assert pay.get_refund(merchant, KEY).status == "succeeded"


@pytest.mark.parametrize("amount", [0, -1, 349.0, "34900", True])
def test_amount_must_be_positive_integer_paise(amount):
    with pytest.raises(ValueError):
        RefundRequest(payment_reference="PAY-1", amount_paise=amount)


def test_concurrent_calls_with_one_key_create_one_operation(merchant):
    pay = MockPayment()
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: pay.refund(merchant, KEY, req()), range(64)))
    assert len({r.operation_id for r in results}) == 1
    assert len(pay.operations(merchant)) == 1


def test_chaos_is_reproducible_with_a_seed(merchant):
    def outcomes():
        pay = MockPayment(Chaos(timeout_rate=0.3, accept_then_timeout_rate=0.2, seed=7))
        out = []
        for i in range(40):
            try:
                out.append(pay.refund(merchant, f"k{i}", req()).status)
            except ProviderTimeout:
                out.append("timeout")
        return out

    first = outcomes()
    assert first == outcomes()
    assert "timeout" in first and "succeeded" in first


def test_payload_hash_ignores_field_order():
    assert payload_hash({"a": 1, "b": 2}) == payload_hash({"b": 2, "a": 1})


@pytest.mark.parametrize("rate", [-0.1, 1.5])
def test_invalid_chaos_rates_rejected(rate):
    with pytest.raises(ValueError):
        Chaos(timeout_rate=rate)
