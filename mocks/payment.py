"""Mock payment provider: refunds with the contract in PROJECT.md section 10."""

from dataclasses import dataclass

from mocks.base import IdempotentMock, Operation


@dataclass(frozen=True)
class RefundRequest:
    payment_reference: str
    amount_paise: int
    currency: str = "INR"
    reason: str = ""

    def __post_init__(self) -> None:
        if type(self.amount_paise) is not int or self.amount_paise <= 0:  # hard rule 3
            raise ValueError("amount_paise must be a positive integer")
        if self.currency != "INR":
            raise ValueError("only INR is supported")


@dataclass(frozen=True)
class RefundResult:
    operation_id: str
    status: str  # processing | succeeded | failed
    amount_paise: int
    failure_reason: str | None = None


def _result(op: Operation) -> RefundResult:
    return RefundResult(op.operation_id, op.status, op.request.amount_paise, op.failure_reason)


class MockPayment(IdempotentMock):
    prefix = "rf"

    def refund(
        self, merchant_id: str, idempotency_key: str, request: RefundRequest
    ) -> RefundResult:
        """Same key + same payload -> same operation; same key + other payload -> 409;
        may raise ProviderTimeout before or after applying (reconcile with get_refund)."""
        return _result(self._call(merchant_id, idempotency_key, request))

    def get_refund(self, merchant_id: str, idempotency_key: str) -> RefundResult | None:
        op = self.get_by_key(merchant_id, idempotency_key)
        return None if op is None else _result(op)
