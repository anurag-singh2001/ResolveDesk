"""Connectors backed by the in-process mocks. Exceptions are translated into outcomes the
executor can act on; nothing here decides whether to retry."""

from datetime import timedelta
from typing import Any

from app.connectors.base import (
    MessagingConnector,
    OrderSourceConnector,
    PaymentConnector,
    RefundOutcome,
    SendOutcome,
    VoucherConnector,
    VoucherOutcome,
    register_connector,
)
from app.core.tenancy import TenantContext
from mocks.base import ProviderTimeout, ProviderUnavailable
from mocks.messaging import MessageRequest
from mocks.payment import RefundRequest
from mocks.registry import get_mock, merchant_id_for
from mocks.vouchers import VoucherRequest


@register_connector
class MockPaymentConnector(PaymentConnector):
    name = "mock_payment"

    @property
    def request_lifetime(self) -> timedelta:
        return timedelta(seconds=get_mock("payment").request_lifetime_s)

    def refund(self, ctx, idempotency_key, payment_reference, amount_paise) -> RefundOutcome:
        request = RefundRequest(payment_reference=payment_reference, amount_paise=amount_paise)
        try:
            r = get_mock("payment").refund(merchant_id_for(ctx.tenant_id), idempotency_key, request)
        except ProviderTimeout:
            return RefundOutcome("unknown")
        except ProviderUnavailable:
            return RefundOutcome("unavailable")  # nothing applied; retry with the same key
        return RefundOutcome(r.status, r.operation_id, r.failure_reason, r.amount_paise)

    def find_refund(self, ctx, idempotency_key) -> RefundOutcome | None:
        r = get_mock("payment").get_refund(merchant_id_for(ctx.tenant_id), idempotency_key)
        if r is None:
            return None
        return RefundOutcome(r.status, r.operation_id, r.failure_reason, r.amount_paise)


@register_connector
class MockVoucherConnector(VoucherConnector):
    name = "mock_vouchers"

    def issue(
        self, ctx, idempotency_key, customer_reference, order_reference, value_paise
    ) -> VoucherOutcome:
        request = VoucherRequest(
            customer_reference=customer_reference,
            value_paise=value_paise,
            order_reference=order_reference,
        )
        try:
            r = get_mock("vouchers").issue(merchant_id_for(ctx.tenant_id), idempotency_key, request)
        except ProviderTimeout:
            return VoucherOutcome("unknown")
        except ProviderUnavailable:
            return VoucherOutcome("unavailable")  # nothing applied; retry with the same key
        return VoucherOutcome(r.status, r.voucher_id, r.failure_reason)

    def find_voucher(self, ctx, idempotency_key) -> VoucherOutcome | None:
        r = get_mock("vouchers").get_voucher(merchant_id_for(ctx.tenant_id), idempotency_key)
        return None if r is None else VoucherOutcome(r.status, r.voucher_id, r.failure_reason)


@register_connector
class MockMessagingConnector(MessagingConnector):
    name = "mock_messaging"

    def send(self, ctx, idempotency_key, to, template, params) -> SendOutcome:
        request = MessageRequest(to=to, template=template, params=tuple(sorted(params.items())))
        try:
            r = get_mock("messaging").send(merchant_id_for(ctx.tenant_id), idempotency_key, request)
        except ProviderTimeout:
            return SendOutcome("unknown")
        except ProviderUnavailable:
            return SendOutcome("unavailable")
        return SendOutcome(r.status, r.message_id)


class _MockOrderSource(OrderSourceConnector):
    mock_name: str

    def fetch_order(self, ctx: TenantContext, external_ref: str) -> dict[str, Any] | None:
        return get_mock(self.mock_name).get_order(merchant_id_for(ctx.tenant_id), external_ref)


@register_connector
class MockPOSConnector(_MockOrderSource):
    name = "mock_pos"
    mock_name = "pos"


@register_connector
class MockDeliveryAppConnector(_MockOrderSource):
    name = "mock_delivery_app"
    mock_name = "delivery_app"
