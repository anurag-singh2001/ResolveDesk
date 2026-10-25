"""Contract tests for the mock payment provider (PROJECT.md section 10)."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from mocks.base import (
    Chaos,
    IdempotencyConflict,
    ProviderTimeout,
    ProviderUnavailable,
    payload_hash,
)
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


def _settle(pay, merchant, key, request, max_attempts=20):
    """What an executor does: call, and after a timeout reconcile by key before retrying."""
    for _ in range(max_attempts):
        try:
            return pay.refund(merchant, key, request)
        except ProviderTimeout:
            found = pay.get_refund(merchant, key)
            if found is not None:
                return found
        except ProviderUnavailable:
            continue
    raise AssertionError(f"{key} never settled")


def test_many_keys_concurrently_under_chaos_one_operation_each(merchant):
    pay = MockPayment(
        Chaos(timeout_rate=0.3, accept_then_timeout_rate=0.2, transient_error_rate=0.1, seed=3)
    )
    keys = [f"P-{i}:refund:1" for i in range(64)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = dict(
            zip(keys, pool.map(lambda k: _settle(pay, merchant, k, req()), keys), strict=True)
        )
    ops = pay.operations(merchant)
    assert len(ops) == len(keys)  # zero duplicates, nothing lost
    assert {op.idempotency_key for op in ops} == set(keys)
    assert {r.operation_id for r in results.values()} == {op.operation_id for op in ops}


def test_seeded_outcomes_do_not_depend_on_call_order(merchant):
    def outcomes(keys):
        pay = MockPayment(Chaos(timeout_rate=0.4, error_rate=0.2, seed=11))
        out = {}
        for k in keys:
            try:
                out[k] = pay.refund(merchant, k, req()).status
            except ProviderTimeout:
                out[k] = "timeout"
        return out

    keys = [f"k{i}" for i in range(30)]
    assert outcomes(keys) == outcomes(list(reversed(keys)))


def test_replay_after_accept_then_timeout_counts_attempts_not_operations(merchant):
    pay = MockPayment(Chaos(accept_then_timeout_rate=1.0))
    for _ in range(3):
        with pytest.raises(ProviderTimeout):
            pay.refund(merchant, KEY, req())
    (op,) = pay.operations(merchant)
    assert op.attempts == 3


def test_transient_error_applies_nothing_and_same_key_retry_succeeds(merchant):
    pay = MockPayment(Chaos(transient_error_rate=1.0))
    with pytest.raises(ProviderUnavailable):
        pay.refund(merchant, KEY, req())
    assert pay.operations(merchant) == []
    pay.set_chaos(Chaos())
    assert pay.refund(merchant, KEY, req()).status == "succeeded"


def test_chaos_for_one_merchant_does_not_affect_another(merchant):
    pay = MockPayment()
    pay.set_chaos(Chaos(timeout_rate=1.0), merchant_id=merchant)
    with pytest.raises(ProviderTimeout):
        pay.refund(merchant, KEY, req())
    assert pay.refund(f"{merchant}_other", KEY, req()).status == "succeeded"


def test_delay_does_not_block_other_calls(merchant):
    pay = MockPayment(Chaos(delay_ms=300))
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: pay.refund(merchant, f"k{i}", req()), range(4)))
    assert time.perf_counter() - started < 0.9  # 4 x 300 ms in parallel, not 1.2 s in series


def test_returned_results_are_snapshots(merchant):
    pay = MockPayment(Chaos(processing_rate=1.0, settle_after_polls=1))
    first = pay.refund(merchant, KEY, req())
    pay.get_refund(merchant, KEY)  # settles the stored operation
    assert first.status == "processing"  # what the caller already holds doesn't change


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def test_a_late_request_lands_within_the_request_lifetime(merchant):
    pay, clock = MockPayment(), _Clock()
    pay.set_clock(clock)
    pay.set_chaos(Chaos(land_late_rate=1.0, land_after_s=pay.request_lifetime_s / 2))
    with pytest.raises(ProviderTimeout):
        pay.refund(merchant, KEY, req())
    assert pay.get_refund(merchant, KEY) is None  # still in flight
    clock.t += pay.request_lifetime_s / 2
    assert pay.get_refund(merchant, KEY).status == "succeeded"  # landed late
    assert len(pay.operations(merchant)) == 1


def test_a_request_past_its_lifetime_never_lands(merchant):
    pay, clock = MockPayment(), _Clock()
    pay.set_clock(clock)
    pay.set_chaos(Chaos(land_late_rate=1.0, land_after_s=pay.request_lifetime_s * 2))
    with pytest.raises(ProviderTimeout):
        pay.refund(merchant, KEY, req())
    clock.t += pay.request_lifetime_s + 1
    assert pay.get_refund(merchant, KEY) is None
    clock.t += pay.request_lifetime_s * 2
    assert pay.get_refund(merchant, KEY) is None  # the contract: it is gone for good
    assert pay.operations(merchant) == []


def test_a_same_key_resend_while_in_flight_makes_one_operation(merchant):
    pay, clock = MockPayment(), _Clock()
    pay.set_clock(clock)
    pay.set_chaos(Chaos(land_late_rate=1.0, land_after_s=5))
    with pytest.raises(ProviderTimeout):
        pay.refund(merchant, KEY, req())
    pay.set_chaos(Chaos())
    first = pay.refund(merchant, KEY, req())
    clock.t += 10
    assert pay.get_refund(merchant, KEY) == first
    assert len(pay.operations(merchant)) == 1
