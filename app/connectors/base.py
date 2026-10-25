"""Connector interfaces + registry (PROJECT.md section 10).

Each tenant picks a connector per kind through settings (`<kind>_connector`), so switching a
tenant to a real provider is a settings change, not a code branch (hard rule 2). The provider
account is always derived from the tenant in the auth context, never from input.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, ClassVar, Literal

from app.core.tenancy import TenantContext

Kind = Literal["payment", "messaging", "orders", "vouchers"]


@dataclass(frozen=True)
class RefundOutcome:
    """Provider truth for one idempotency key. `unknown` = no answer; reconcile before retry."""

    status: Literal["processing", "succeeded", "failed", "unknown", "unavailable"]
    provider_reference: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class SendOutcome:
    status: Literal["processing", "succeeded", "failed", "unknown", "unavailable"]
    provider_reference: str | None = None


class Connector(ABC):
    name: ClassVar[str]
    kind: ClassVar[Kind]


class PaymentConnector(Connector):
    kind = "payment"
    # Provider contract: a request (e.g. one that timed out) is applied within this long of
    # being sent or never. Releasing quarantined money waits longer than this (E4.4).
    request_lifetime: ClassVar[timedelta]

    @abstractmethod
    def refund(
        self, ctx: TenantContext, idempotency_key: str, payment_reference: str, amount_paise: int
    ) -> RefundOutcome: ...

    @abstractmethod
    def find_refund(self, ctx: TenantContext, idempotency_key: str) -> RefundOutcome | None: ...


@dataclass(frozen=True)
class VoucherOutcome:
    """Provider truth for one voucher key. `unknown` = no answer; reconcile before retry."""

    status: Literal["processing", "succeeded", "failed", "unknown", "unavailable"]
    provider_reference: str | None = None
    failure_reason: str | None = None


class VoucherConnector(Connector):
    kind = "vouchers"

    @abstractmethod
    def issue(
        self,
        ctx: TenantContext,
        idempotency_key: str,
        customer_reference: str,
        order_reference: str,
        value_paise: int,
    ) -> VoucherOutcome: ...

    @abstractmethod
    def find_voucher(self, ctx: TenantContext, idempotency_key: str) -> VoucherOutcome | None: ...


class MessagingConnector(Connector):
    kind = "messaging"

    @abstractmethod
    def send(
        self, ctx: TenantContext, idempotency_key: str, to: str, template: str, params: dict
    ) -> SendOutcome: ...


class OrderSourceConnector(Connector):
    kind = "orders"

    @abstractmethod
    def fetch_order(self, ctx: TenantContext, external_ref: str) -> dict[str, Any] | None:
        """The source system's current view of an order, in canonical field names."""


_REGISTRY: dict[str, type[Connector]] = {}


def register_connector(cls: type[Connector]) -> type[Connector]:
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"connector {cls.name!r} is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def get_connector(name: str, kind: Kind) -> Connector:
    cls = _REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"unknown connector {name!r}")
    if cls.kind != kind:
        raise TypeError(f"connector {name!r} is a {cls.kind} connector, not {kind}")
    return cls()


def connector_for(settings: dict[str, Any], kind: Kind) -> Connector:
    """The connector a tenant's effective settings select for this kind."""
    return get_connector(settings[f"{kind}_connector"], kind)


def registered_connectors() -> dict[str, type[Connector]]:
    return dict(_REGISTRY)
