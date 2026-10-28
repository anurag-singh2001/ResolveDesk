"""Deterministic remedies (the no-LLM path, PROJECT.md section 19 day 2).

Which rule applies to a category comes from the vertical pack (`remedies`); amounts come
from tenant settings and the order's own data. Nothing here trusts the customer's text: the
customer picks a category, code reads the facts. The LLM pipeline (E3) will propose through
the same `create_proposal`, so both paths get the same validation and approvals.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.free_item_voucher import MIN_VOUCHER_PAISE  # noqa: F401  (re-exported)
from app.core.business_time import business_date
from app.core.models import Case, Fulfilment, LineItem
from app.core.money import percent_of
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.engine.eligibility import order_facts
from app.engine.privacy import ESCALATION_REASON, PRIVACY_CATEGORY
from app.engine.proposals import create_proposal


@dataclass(frozen=True)
class Remedy:
    action: str | None  # None: nothing to propose (apology / escalate)
    params: dict
    reason: str
    outcome: str  # proposed | apology | escalate


def decide_remedy(session: Session, case: Case) -> Remedy:
    if case.category == PRIVACY_CATEGORY:  # never a payout: a person handles it (S5.5)
        return Remedy(None, {}, ESCALATION_REASON, "escalate")
    rule = tenant_pack(session).remedies.get(case.category)
    if rule is None or case.transaction_id is None:
        return Remedy(None, {}, "no automatic remedy for this category", "escalate")
    order, facts = order_facts(session, case.transaction_id)
    s = facts.settings
    order_ref = str(order.id)

    if rule == "late_tiers":
        f = session.scalar(select(Fulfilment).where(Fulfilment.transaction_id == order.id))
        if f is None or f.completed_at is None:
            return Remedy(None, {}, "order not completed yet", "escalate")
        late = max(timedelta(0), f.completed_at - f.promised_at)
        minutes = int(late.total_seconds() // 60)
        why = f"{minutes} min late"
        # The cause comes from the delivery record (connector data), never the customer's text.
        cause = (f.attributes or {}).get("delay_cause")
        if cause is not None and cause in s["late_delivery_excluded_causes"]:
            return Remedy(None, {}, f"{why}; delay cause on record: {cause}", "apology")
        placed_on = business_date(order.placed_at, s)  # the tenant's calendar, not UTC
        tier = late_tier(s["late_delivery_tiers"], minutes, placed_on)
        if tier is None or tier["remedy"] == "apology":
            return Remedy(None, {}, f"{why}: apology tier", "apology")
        if tier["remedy"] == "voucher":
            return _voucher(order_ref, order.total_paise, s, why)
        # The tier's percent is what the tenant asks for; refund_max_percent stays the ceiling.
        percent = min(tier.get("percent", 0), s["refund_max_percent"])
        amount = min(percent_of(order.total_paise, percent), facts.refundable_paise)
        return _refund(order_ref, amount, f"{why}: {percent}% refund tier")

    if rule == "refund_missing":
        lines = session.scalars(select(LineItem).where(LineItem.transaction_id == order.id))
        missing = sum(li.unit_price_paise * (li.quantity - li.quantity_fulfilled) for li in lines)
        if missing <= 0:
            return Remedy(None, {}, "no missing items on record for this order", "escalate")
        cap = percent_of(order.total_paise, s["refund_max_percent"])
        return _refund(order_ref, min(missing, cap, facts.refundable_paise), "missing items")

    return _voucher(order_ref, order.total_paise, s, case.category.replace("_", " "))


def late_tier(tiers: list[dict], minutes: int, placed_on: date) -> dict | None:
    """The highest tier reached among the tiers in force on the order date.

    A tier may carry `effective_from` / `effective_to` (ISO dates, `to` exclusive): the same
    order-date rule as policy versions, so changing tiers never re-prices older orders.
    """

    def in_force(t: dict) -> bool:
        start, end = t.get("effective_from"), t.get("effective_to")
        return (start is None or date.fromisoformat(start) <= placed_on) and (
            end is None or placed_on < date.fromisoformat(end)
        )

    reached = [t for t in tiers if in_force(t) and t["min_minutes_late"] <= minutes]
    return max(reached, key=lambda t: t["min_minutes_late"], default=None)


def _refund(order_ref: str, amount: int, why: str) -> Remedy:
    if amount <= 0:
        return Remedy(None, {}, "nothing left to refund on this order", "escalate")
    params = {"transaction_id": order_ref, "amount_paise": amount, "reason": why}
    return Remedy("refund", params, why, "proposed")


_RUPEE = 100


def _voucher(order_ref: str, order_total_paise: int, settings: dict, why: str) -> Remedy:
    # Never more than the customer paid (voucher_percent of the order total, default 100),
    # never above the tenant's hard cap or its auto-approve cap. The order total is used, not a
    # line total: decide_remedy has no per-item link from the case, so we don't guess one.
    # .get: a pack stored in the DB before voucher_percent existed lacks the key (100 = default).
    scaled = percent_of(order_total_paise, settings.get("voucher_percent", 100))
    value = min(settings["voucher_auto_approve_max_paise"], settings["voucher_max_paise"], scaled)
    value -= value % _RUPEE  # whole rupees, rounded down
    if value < MIN_VOUCHER_PAISE:
        return Remedy(None, {}, "order too small for a voucher; a person decides", "escalate")
    params = {"transaction_id": order_ref, "value_paise": value, "reason": why}
    return Remedy("free_item_voucher", params, why, "proposed")


def propose_for_case(
    session: Session, ctx: TenantContext, case: Case
) -> tuple[Remedy, uuid.UUID | None]:
    remedy = decide_remedy(session, case)
    if remedy.action is None:
        return remedy, None
    proposal = create_proposal(
        session,
        ctx.tenant_id,
        case_id=case.id,
        action=remedy.action,
        params=remedy.params,
        reason=f"deterministic rule: {remedy.reason}",
    )
    return remedy, proposal.id
