"""Deterministic remedies (the no-LLM path, PROJECT.md section 19 day 2).

Which rule applies to a category comes from the vertical pack (`remedies`); amounts come
from tenant settings and the order's own data. Nothing here trusts the customer's text: the
customer picks a category, code reads the facts. The LLM pipeline (E3) will propose through
the same `create_proposal`, so both paths get the same validation and approvals.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Case, Fulfilment, LineItem
from app.core.money import percent_of
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.engine.eligibility import order_facts
from app.engine.proposals import create_proposal


@dataclass(frozen=True)
class Remedy:
    action: str | None  # None: nothing to propose (apology / escalate)
    params: dict
    reason: str
    outcome: str  # proposed | apology | escalate


def decide_remedy(session: Session, case: Case) -> Remedy:
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
        tier = max(
            (t for t in s["late_delivery_tiers"] if t["min_minutes_late"] <= minutes),
            key=lambda t: t["min_minutes_late"],
            default=None,
        )
        why = f"{minutes} min late"
        if tier is None or tier["remedy"] == "apology":
            return Remedy(None, {}, f"{why}: apology tier", "apology")
        if tier["remedy"] == "voucher":
            return _voucher(order_ref, s, why)
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

    return _voucher(order_ref, s, case.category.replace("_", " "))


def _refund(order_ref: str, amount: int, why: str) -> Remedy:
    if amount <= 0:
        return Remedy(None, {}, "nothing left to refund on this order", "escalate")
    params = {"transaction_id": order_ref, "amount_paise": amount, "reason": why}
    return Remedy("refund", params, why, "proposed")


def _voucher(order_ref: str, settings: dict, why: str) -> Remedy:
    # The auto-approve cap: the largest voucher the tenant lets through without a human.
    value = min(settings["voucher_auto_approve_max_paise"], settings["voucher_max_paise"])
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
