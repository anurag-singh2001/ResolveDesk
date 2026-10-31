"""Facts for deterministic eligibility, read inside the tenant's transaction.

The refundable balance counts every refund that holds or moved money (reserved, submitted,
succeeded, unknown, pending_reconciliation): an in-flight refund must block a second one.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.actions.base import Facts, registered_actions
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Payment,
    RefundOperation,
    Transaction,
)
from app.core.settings_resolver import effective_settings

HOLDING_STATUSES = ("reserved", "submitted", "succeeded", "unknown", "pending_reconciliation")
CAPTURED_STATUSES = ("captured", "partially_refunded")


def refundable_paise(
    session: Session, transaction_id: uuid.UUID, exclude_proposal: uuid.UUID | None = None
) -> int:
    captured = session.scalar(
        select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(
            Payment.transaction_id == transaction_id, Payment.status.in_(CAPTURED_STATUSES)
        )
    )
    held = select(func.coalesce(func.sum(RefundOperation.amount_paise), 0)).where(
        RefundOperation.transaction_id == transaction_id,
        RefundOperation.status.in_(HOLDING_STATUSES),
    )
    if exclude_proposal is not None:
        held = held.where(RefundOperation.proposal_id != exclude_proposal)
    return int(captured) - int(session.scalar(held))


FAIR_USE_WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class FairUse:
    grants_30d: int
    max_grants_30d: int

    @property
    def ok(self) -> bool:
        return self.grants_30d < self.max_grants_30d

    def checks(self) -> dict:
        return {
            "fair_use_ok": self.ok,
            "fair_use_grants_30d": self.grants_30d,
            "fair_use_max_grants_30d": self.max_grants_30d,
        }


def fair_use(
    session: Session,
    customer_id: uuid.UUID,
    settings: dict,
    now: datetime,
    exclude_proposal: uuid.UUID | None = None,
) -> FairUse:
    """Refunds and vouchers approved (by a person or a tenant rule) for this customer in the
    30 days before `now`. Approval is the grant decision: vouchers have no execution yet, and
    an approved refund that later failed still counts, which only sends more cases to a
    person. A signal for review, never a denial (PROJECT.md section 2). RLS keeps it to the
    session's tenant; `customer_id` comes from the case record, never from input."""
    grant_actions = [name for name, cls in registered_actions().items() if cls.counts_as_grant]
    query = (
        select(func.count())
        .select_from(Approval)
        .join(ActionProposal, ActionProposal.id == Approval.proposal_id)
        .join(Case, Case.id == ActionProposal.case_id)
        .where(
            Case.customer_id == customer_id,
            Approval.decision == "approved",
            ActionProposal.action.in_(grant_actions),
            Approval.decided_at > now - FAIR_USE_WINDOW,
            Approval.decided_at <= now,
        )
    )
    if exclude_proposal is not None:
        query = query.where(ActionProposal.id != exclude_proposal)
    return FairUse(int(session.scalar(query)), settings["fair_use_max_grants_30d"])


# Always delivery apps, whatever a tenant sets: a setting can add sources but never remove these
# (both tenants' policies say these apps refund their own orders).
AGGREGATOR_SOURCES_FLOOR = frozenset({"swiggy", "zomato"})


def is_aggregator_order(order: Transaction, settings: dict) -> bool:
    """Placed through a third-party delivery app. The channel is the order's `source`; the
    sources that count are the code floor plus the setting `aggregator_order_sources`, compared
    case-insensitively, so an override can add a delivery app but cannot hide swiggy or zomato."""
    configured = settings.get("aggregator_order_sources") or []
    names = AGGREGATOR_SOURCES_FLOOR | {str(x).strip().lower() for x in configured}
    return str(order.source or "").strip().lower() in names


def order_facts(
    session: Session,
    transaction_id: uuid.UUID,
    *,
    lock: bool = False,
    exclude_proposal: uuid.UUID | None = None,
) -> tuple[Transaction, Facts]:
    """Facts for one order. lock=True takes SELECT ... FOR UPDATE on the order row first, so
    concurrent reservations against the same order are serialised (PROJECT.md section 7)."""
    query = select(Transaction).where(Transaction.id == transaction_id)
    order = session.scalars(query.with_for_update() if lock else query).one_or_none()
    if order is None:
        raise LookupError("order not found")
    settings = effective_settings(session, brand_id=order.brand_id, location_id=order.location_id)
    if is_aggregator_order(order, settings):
        # The delivery app took the payment and refunds it (both tenants' policies). Every
        # refund check and option reads this one setting, so none of them can offer a refund.
        settings = {**settings, "refund_channel": "aggregator_only"}
    facts = Facts(
        settings=settings,
        order_total_paise=order.total_paise,
        refundable_paise=refundable_paise(session, order.id, exclude_proposal),
    )
    return order, facts
