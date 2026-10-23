"""Shared chaos and idempotency behaviour for the mocks."""

import hashlib
import json
import random
import threading
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


class ProviderTimeout(Exception):
    """No response. The request may or may not have been applied: reconcile by key."""


class IdempotencyConflict(Exception):
    """Same idempotency key, different payload. A real provider answers HTTP 409."""

    http_status = 409


@dataclass
class Chaos:
    """Failure injection. Rates are probabilities per call; seed makes runs reproducible."""

    timeout_rate: float = 0.0  # time out before accepting: nothing happens
    accept_then_timeout_rate: float = 0.0  # apply the request, then time out
    error_rate: float = 0.0  # provider declines (operation recorded as failed)
    processing_rate: float = 0.0  # accepted as "processing", settles after polls
    settle_after_polls: int = 2
    delay_ms: int = 0
    seed: int = 0

    def __post_init__(self) -> None:
        for name in ("timeout_rate", "accept_then_timeout_rate", "error_rate", "processing_rate"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


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
    attempts: int = 1  # how many calls carried this key (duplicates never re-apply)
    extra: dict = field(default_factory=dict)


class IdempotentMock:
    """Stores one operation per (merchant, idempotency key) and replays it on repeats."""

    prefix = "op"

    def __init__(self, chaos: Chaos | None = None) -> None:
        self._lock = threading.Lock()
        self._ops: dict[tuple[str, str], Operation] = {}
        self.set_chaos(chaos or Chaos())

    def set_chaos(self, chaos: Chaos) -> None:
        with self._lock:
            self.chaos = chaos
            self._rng = random.Random(chaos.seed)

    def reset(self) -> None:
        with self._lock:
            self._ops.clear()
            self._rng = random.Random(self.chaos.seed)

    def _roll(self, rate: float) -> bool:
        return rate > 0 and self._rng.random() < rate

    def _call(self, merchant_id: str, idempotency_key: str, request: Any) -> Operation:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        if self.chaos.delay_ms:
            time.sleep(self.chaos.delay_ms / 1000)
        digest = payload_hash(request)
        with self._lock:
            if self._roll(self.chaos.timeout_rate):
                raise ProviderTimeout("timed out before the request was accepted")
            key = (merchant_id, idempotency_key)
            op = self._ops.get(key)
            if op is not None:
                if op.request_hash != digest:
                    raise IdempotencyConflict(
                        f"key {idempotency_key!r} reused with another payload"
                    )
                op.attempts += 1
                self._advance(op)
            else:
                op = self._create(merchant_id, idempotency_key, digest, request)
                self._ops[key] = op
            if self._roll(self.chaos.accept_then_timeout_rate):
                raise ProviderTimeout("timed out after the request was accepted")
            return op

    def _create(self, merchant_id, idempotency_key, digest, request) -> Operation:
        n = sum(1 for m, _ in self._ops if m == merchant_id) + 1
        op = Operation(
            operation_id=f"{self.prefix}_{hashlib.sha256(f'{merchant_id}:{n}'.encode()).hexdigest()[:16]}",
            idempotency_key=idempotency_key,
            request_hash=digest,
            request=request,
            status="succeeded",
        )
        if self._roll(self.chaos.error_rate):
            op.status, op.failure_reason = "failed", "declined_by_provider"
        elif self._roll(self.chaos.processing_rate):
            op.status, op.polls_left = "processing", self.chaos.settle_after_polls
        return op

    def _advance(self, op: Operation) -> None:
        if op.status == "processing":
            op.polls_left -= 1
            if op.polls_left <= 0:
                op.status = "succeeded"

    def get_by_key(self, merchant_id: str, idempotency_key: str) -> Operation | None:
        """Reconciliation: what happened to this key? Never subject to chaos."""
        with self._lock:
            op = self._ops.get((merchant_id, idempotency_key))
            if op is not None:
                self._advance(op)
            return op

    def operations(self, merchant_id: str) -> list[Operation]:
        with self._lock:
            return [op for (m, _), op in self._ops.items() if m == merchant_id]
