"""Facts for deterministic eligibility, read inside the tenant's transaction.

The refundable balance counts every refund that holds or moved money (reserved, submitted,
succeeded, unknown, pending_reconciliation): an in-flight refund must block a second one.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.actions.base import Facts
from app.core.models import Payment, RefundOperation, Transaction
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
    facts = Facts(
        settings=effective_settings(
            session, brand_id=order.brand_id, location_id=order.location_id
        ),
        order_total_paise=order.total_paise,
        refundable_paise=refundable_paise(session, order.id, exclude_proposal),
    )
    return order, facts
