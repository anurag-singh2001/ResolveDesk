"""Mock WhatsApp-like messaging: idempotent sends and an outbox to assert on."""

from dataclasses import dataclass

from mocks.base import IdempotentMock, Operation


@dataclass(frozen=True)
class MessageRequest:
    to: str
    template: str
    params: tuple[tuple[str, str], ...] = ()  # tuple of pairs: hashable and order-stable


@dataclass(frozen=True)
class MessageResult:
    message_id: str
    status: str  # succeeded = delivered to the channel | failed | processing


def _result(op: Operation) -> MessageResult:
    return MessageResult(op.operation_id, op.status)


class MockMessaging(IdempotentMock):
    prefix = "msg"

    def send(
        self, merchant_id: str, idempotency_key: str, request: MessageRequest
    ) -> MessageResult:
        return _result(self._call(merchant_id, idempotency_key, request))

    def get_message(self, merchant_id: str, idempotency_key: str) -> MessageResult | None:
        op = self.get_by_key(merchant_id, idempotency_key)
        return None if op is None else _result(op)

    def outbox(self, merchant_id: str) -> list[MessageRequest]:
        """Messages that actually went out (one per key, however often it was retried)."""
        return [op.request for op in self.operations(merchant_id) if op.status == "succeeded"]
