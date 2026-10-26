"""Mock voucher service: issues a voucher for a customer's future order, idempotently."""

from dataclasses import dataclass

from mocks.base import IdempotentMock, Operation


@dataclass(frozen=True)
class VoucherRequest:
    customer_reference: str
    value_paise: int
    order_reference: str
    currency: str = "INR"

    def __post_init__(self) -> None:
        if type(self.value_paise) is not int or self.value_paise <= 0:  # hard rule 3
            raise ValueError("value_paise must be a positive integer")
        if self.currency != "INR":
            raise ValueError("only INR is supported")


@dataclass(frozen=True)
class VoucherResult:
    voucher_id: str
    status: str  # processing | succeeded | failed
    value_paise: int
    failure_reason: str | None = None


def _result(op: Operation) -> VoucherResult:
    return VoucherResult(op.operation_id, op.status, op.request.value_paise, op.failure_reason)


class MockVouchers(IdempotentMock):
    prefix = "vc"
    request_type = VoucherRequest

    def issue(
        self, merchant_id: str, idempotency_key: str, request: VoucherRequest
    ) -> VoucherResult:
        """Same key + same payload -> same voucher; same key + other payload -> 409."""
        return _result(self._call(merchant_id, idempotency_key, request))

    def get_voucher(self, merchant_id: str, idempotency_key: str) -> VoucherResult | None:
        op = self.get_by_key(merchant_id, idempotency_key)
        return None if op is None else _result(op)
