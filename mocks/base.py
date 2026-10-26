"""Shared chaos and idempotency behaviour for the mocks."""

import dataclasses
import hashlib
import json
import random
import threading
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


class ProviderTimeout(Exception):
    """No response. The request may or may not have been applied: reconcile by key."""


class ProviderUnavailable(Exception):
    """Transient 5xx/429 before the request was accepted. Nothing applied; retry with the SAME
    key (rule 5)."""

    retryable = True


class IdempotencyConflict(Exception):
    """Same idempotency key, different payload. A real provider answers HTTP 409."""

    http_status = 409


@dataclass(frozen=True)
class Chaos:
    """Failure injection. Rates are probabilities per call; seed makes runs reproducible.

    Each outcome is drawn from (seed, merchant, key, attempt number), so it does not depend on
    thread scheduling or on other merchants' traffic.
    """

    timeout_rate: float = 0.0  # time out before accepting: nothing happens
    transient_error_rate: float = 0.0  # 5xx/429 before accepting: nothing happens, retryable
    accept_then_timeout_rate: float = 0.0  # apply the request, then time out
    error_rate: float = 0.0  # provider declines: recorded as failed, final for that key
    processing_rate: float = 0.0  # accepted as "processing", settles after polls
    settle_after_polls: int = 2
    # Time out while the request is still in flight: it lands (is applied) land_after_s later,
    # unless that is past the provider's request lifetime, in which case it never lands.
    land_late_rate: float = 0.0
    land_after_s: float = 0.0
    delay_ms: int = 0
    seed: int = 0

    def __post_init__(self) -> None:
        for name in (
            "timeout_rate",
            "transient_error_rate",
            "accept_then_timeout_rate",
            "error_rate",
            "processing_rate",
            "land_late_rate",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.land_after_s < 0:
            raise ValueError("land_after_s must not be negative")


def payload_hash(payload: Any) -> str:
    """sha256 of canonical JSON, so field order never changes the hash."""
    data = asdict(payload) if is_dataclass(payload) else payload
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class Operation:
    operation_id: str
    idempotency_key: str
    request_hash: str
    request: Any
    status: str  # processing | succeeded | failed
    failure_reason: str | None = None
    polls_left: int = 0
    attempts: int = 1  # calls that carried this key and reached the provider
    extra: dict = field(default_factory=dict)


class ChaosByMerchant:
    """A default Chaos plus per-merchant overrides (one tenant's chaos never hits another)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._default = Chaos()
        self._by_merchant: dict[str, Chaos] = {}
        self._calls: dict[tuple[str, str], int] = {}

    def set(self, chaos: Chaos, merchant_id: str | None = None) -> None:
        with self._lock:
            if merchant_id is None:
                self._default = chaos
            else:
                self._by_merchant[merchant_id] = chaos

    def get(self, merchant_id: str | None = None) -> Chaos:
        with self._lock:
            return self._by_merchant.get(merchant_id, self._default)

    def reset(self) -> None:
        with self._lock:
            self._default = Chaos()
            self._by_merchant.clear()
            self._calls.clear()

    def draw(self, merchant_id: str, key: str) -> tuple[Chaos, random.Random]:
        """The chaos for this call and an RNG unique to (seed, merchant, key, attempt)."""
        with self._lock:
            chaos = self._by_merchant.get(merchant_id, self._default)
            attempt = self._calls.get((merchant_id, key), 0) + 1
            self._calls[(merchant_id, key)] = attempt
        return chaos, random.Random(f"{chaos.seed}:{merchant_id}:{key}:{attempt}")


def hit(rng: random.Random, rate: float) -> bool:
    # Always consume one draw, so each roll's outcome doesn't depend on earlier rates being 0.
    return rng.random() < rate


@dataclass(frozen=True)
class _InFlight:
    sent_at: float
    lands_at: float
    request_hash: str
    request: Any


class IdempotentMock:
    """Stores one operation per (merchant, idempotency key) and replays it on repeats.

    Provider contract on late requests: a request that timed out may still be applied later,
    but never more than `request_lifetime_s` after it was sent. After that, a lookup by key
    that finds nothing is final. Operators rely on this to release quarantined money (E4.4).
    """

    prefix = "op"
    request_lifetime_s: float = 60.0

    def __init__(self, chaos: Chaos | None = None) -> None:
        self._lock = threading.Lock()
        self._ops: dict[tuple[str, str], Operation] = {}
        self._inflight: dict[tuple[str, str], _InFlight] = {}
        self._clock = time.time
        self.chaos = ChaosByMerchant()
        if chaos is not None:
            self.chaos.set(chaos)

    def set_chaos(self, chaos: Chaos, merchant_id: str | None = None) -> None:
        self.chaos.set(chaos, merchant_id)

    def set_clock(self, clock) -> None:
        """Seconds since the epoch, like time.time (tests move time forward)."""
        self._clock = clock

    def now(self) -> float:
        return self._clock()

    def reset(self) -> None:
        with self._lock:
            self._ops.clear()
            self._inflight.clear()
            self._clock = time.time
        self.chaos.reset()

    def _land(self, merchant_id: str, key: str) -> None:
        """Apply a late request whose time has come; drop one past the request lifetime.
        Caller holds the lock."""
        flight = self._inflight.get((merchant_id, key))
        if flight is None:
            return
        now = self.now()
        if (merchant_id, key) in self._ops:
            del self._inflight[(merchant_id, key)]  # a later same-key call already applied it
        elif flight.lands_at - flight.sent_at > self.request_lifetime_s:
            if now - flight.sent_at > self.request_lifetime_s:
                del self._inflight[(merchant_id, key)]  # expired: it never lands
        elif now >= flight.lands_at:
            op = self._create(merchant_id, key, flight.request_hash, flight.request)
            self._ops[(merchant_id, key)] = op
            del self._inflight[(merchant_id, key)]

    def _call(self, merchant_id: str, idempotency_key: str, request: Any) -> Operation:
        """Returns a snapshot of the stored operation (safe to read after the lock)."""
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        chaos, rng = self.chaos.draw(merchant_id, idempotency_key)
        if chaos.delay_ms:
            time.sleep(chaos.delay_ms / 1000)  # outside the lock: slow calls don't block others
        digest = payload_hash(request)
        timeout, transient = hit(rng, chaos.timeout_rate), hit(rng, chaos.transient_error_rate)
        accept_then_timeout = hit(rng, chaos.accept_then_timeout_rate)
        declined, processing = hit(rng, chaos.error_rate), hit(rng, chaos.processing_rate)
        late = hit(rng, chaos.land_late_rate)
        if timeout:
            raise ProviderTimeout("timed out before the request was accepted")
        if transient:
            raise ProviderUnavailable("provider temporarily unavailable")
        with self._lock:
            key = (merchant_id, idempotency_key)
            self._land(merchant_id, idempotency_key)
            op = self._ops.get(key)
            if op is None and late:
                if key not in self._inflight:
                    sent = self.now()
                    self._inflight[key] = _InFlight(
                        sent, sent + chaos.land_after_s, digest, request
                    )
                raise ProviderTimeout("timed out; the request is still in flight")
            if op is not None:
                if op.request_hash != digest:
                    raise IdempotencyConflict(
                        f"key {idempotency_key!r} reused with another payload"
                    )
                op.attempts += 1
                self._advance(op)
            else:
                op = self._create(merchant_id, idempotency_key, digest, request)
                if declined:
                    op.status, op.failure_reason = "failed", "declined_by_provider"
                elif processing:
                    op.status, op.polls_left = "processing", chaos.settle_after_polls
                self._ops[key] = op
                self._inflight.pop(key, None)  # an earlier in-flight copy dedups onto this op
            snapshot = dataclasses.replace(op, extra=dict(op.extra))
        if accept_then_timeout:
            raise ProviderTimeout("timed out after the request was accepted")
        return snapshot

    def _create(self, merchant_id, idempotency_key, digest, request) -> Operation:
        n = sum(1 for m, _ in self._ops if m == merchant_id) + 1
        token = hashlib.sha256(f"{self.prefix}:{merchant_id}:{n}".encode()).hexdigest()[:16]
        return Operation(
            operation_id=f"{self.prefix}_{token}",
            idempotency_key=idempotency_key,
            request_hash=digest,
            request=request,
            status="succeeded",
        )

    @staticmethod
    def _advance(op: Operation) -> None:
        if op.status == "processing":
            op.polls_left -= 1
            if op.polls_left <= 0:
                op.status = "succeeded"

    def get_by_key(self, merchant_id: str, idempotency_key: str) -> Operation | None:
        """Reconciliation: what happened to this key? Never subject to chaos."""
        with self._lock:
            self._land(merchant_id, idempotency_key)
            op = self._ops.get((merchant_id, idempotency_key))
            if op is None:
                return None
            self._advance(op)
            return dataclasses.replace(op, extra=dict(op.extra))

    def operations(self, merchant_id: str) -> list[Operation]:
        with self._lock:
            return [
                dataclasses.replace(op, extra=dict(op.extra))
                for (m, _), op in self._ops.items()
                if m == merchant_id
            ]
