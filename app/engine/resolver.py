"""Deterministic remedies (the no-LLM path, PROJECT.md section 19 day 2).

Which rule applies to a category comes from the vertical pack (`remedies`); amounts come
from tenant settings and the order's own data. Nothing here trusts the customer's text: the
customer picks a category, code reads the facts. The LLM pipeline (E3) will propose through
the same `create_proposal`, so both paths get the same validation and approvals.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.free_item_voucher import MIN_VOUCHER_PAISE  # noqa: F401  (re-exported)
from app.core import audit
from app.core.business_time import business_date
from app.core.models import Case, Fulfilment, LineItem, Transaction
from app.core.money import percent_of
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.core.verticals import RefundPercentOption, option_code, rule_options
from app.engine.eligibility import order_facts
from app.engine.privacy import ESCALATION_REASON, PRIVACY_CATEGORY
from app.engine.proposals import create_proposal


@dataclass(frozen=True)
class Remedy:
    action: str | None  # None: nothing to propose (apology / escalate)
    params: dict
    reason: str
    outcome: str  # proposed | apology | escalate
    fallback_from: str | None = None  # the customer's pick, when it could not be honoured
    # Which rule set the amount: structured codes + params (never free text), stored with the
    # proposal and rendered from templates (app/engine/sources.py).
    basis: tuple[dict, ...] = ()


class InvalidRemedyChoice(ValueError):
    """The chosen option is not one the category's rule allows."""


@dataclass(frozen=True)
class ChoiceOption:
    code: str
    remedy: Remedy  # what the rule gives for this option on this order, computed by code


def decide_remedy(session: Session, case: Case, choice: str | None = None) -> Remedy:
    """The remedy the rules give this case. When the category's rule lists several options,
    the customer's pick (`choice`, else the stored cases.remedy_choice) selects one; no pick
    means the first option that works. An explicit `choice` outside the rule raises; a stored
    one that the pack no longer lists is ignored (the rule changed after the pick)."""
    if case.category == PRIVACY_CATEGORY:  # never a payout: a person handles it (S5.5)
        return Remedy(None, {}, ESCALATION_REASON, "escalate")
    rule = tenant_pack(session).remedies.get(case.category)
    if rule is None or case.transaction_id is None:
        return Remedy(None, {}, "no automatic remedy for this category", "escalate")
    order, facts = order_facts(session, case.transaction_id)
    options = _priced_options(session, order, facts, case.category, rule)
    by_code = {o.code: o for o in options}
    explicit = choice is not None
    picked = choice if explicit else getattr(case, "remedy_choice", None)
    if explicit and picked not in by_code:
        raise InvalidRemedyChoice(f"{picked!r} is not an option for this category")
    if picked is not None and picked in by_code and by_code[picked].remedy.action:
        return by_code[picked].remedy
    first = next((o.remedy for o in options if o.remedy.action), options[0].remedy)
    if picked is not None and picked in by_code and first.action:
        # The pick is in the rule but yields nothing now (e.g. nothing left to refund): give the
        # first workable option instead of escalating; callers audit it via fallback_from.
        return replace(first, fallback_from=picked)
    return first


def remedy_options(
    session: Session, order: Transaction, facts, category: str
) -> list[ChoiceOption]:
    """Options a customer may choose between for this order and category: only those the rule
    lists AND that currently yield a proposal. Fewer than two means there is nothing to choose."""
    rule = tenant_pack(session).remedies.get(category)
    if rule is None or category == PRIVACY_CATEGORY:
        return []
    return [o for o in _priced_options(session, order, facts, category, rule) if o.remedy.action]


def _priced_options(
    session: Session, order: Transaction, facts, category: str, rule
) -> list[ChoiceOption]:
    return [
        ChoiceOption(option_code(o), _apply(session, order, facts, category, o))
        for o in rule_options(rule)
    ]


def _apply(session: Session, order: Transaction, facts, category: str, option) -> Remedy:
    s = facts.settings
    order_ref = str(order.id)

    if isinstance(option, RefundPercentOption):
        if s["refund_channel"] != "tenant_gateway":
            # Placed through a delivery app: that app refunds it, so no refund option exists
            # (the customer is never shown a request we could not honour).
            return Remedy(None, {}, "the delivery app refunds this order", "escalate")
        # The option's percent is what the pack offers; refund_max_percent stays the ceiling.
        percent = min(option.refund_percent, s["refund_max_percent"])
        amount = min(percent_of(order.total_paise, percent), facts.refundable_paise)
        return _refund(
            order_ref, amount, f"customer chose a {percent}% refund",
            _percent_basis("refund_choice", percent, amount, order.total_paise, facts),
        )  # fmt: skip

    if option == "late_tiers":
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
            return _voucher(order_ref, order.total_paise, s, why, (_tier_basis(tier, minutes),))
        # The tier's percent is what the tenant asks for; refund_max_percent stays the ceiling.
        percent = min(tier.get("percent", 0), s["refund_max_percent"])
        amount = min(percent_of(order.total_paise, percent), facts.refundable_paise)
        return _refund(
            order_ref, amount, f"{why}: {percent}% refund tier",
            (_tier_basis(tier, minutes),)
            + _percent_basis("refund_percent", percent, amount, order.total_paise, facts),
        )  # fmt: skip

    if option == "refund_missing":
        missing = missing_items_paise(session, order.id)
        if missing <= 0:
            return Remedy(None, {}, "no missing items on record for this order", "escalate")
        cap = percent_of(order.total_paise, s["refund_max_percent"])
        amount = min(missing, cap, facts.refundable_paise)
        basis = {"code": "refund_missing", "params": {"capped": amount < missing}}
        return _refund(order_ref, amount, "missing items", (basis,))

    return _voucher(order_ref, order.total_paise, s, category.replace("_", " "))


def missing_items_paise(session: Session, order_id: uuid.UUID) -> int:
    """Value of the items the order record shows as not delivered (unit price x shortfall)."""
    lines = session.scalars(select(LineItem).where(LineItem.transaction_id == order_id))
    return sum(li.unit_price_paise * (li.quantity - li.quantity_fulfilled) for li in lines)


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


def _tier_basis(tier: dict, minutes: int) -> dict:
    return {
        "code": "late_tier",
        "params": {"tier_minutes": tier["min_minutes_late"], "minutes": minutes},
    }


def _percent_basis(code: str, percent: int, amount: int, total: int, facts) -> tuple[dict, ...]:
    """A percent-of-order refund; flags when the order's refundable balance cut it short."""
    capped = amount < percent_of(total, percent) and amount == facts.refundable_paise
    return ({"code": code, "params": {"percent": percent, "capped": capped}},)


def _refund(order_ref: str, amount: int, why: str, basis: tuple[dict, ...] = ()) -> Remedy:
    if amount <= 0:
        return Remedy(None, {}, "nothing left to refund on this order", "escalate")
    params = {"transaction_id": order_ref, "amount_paise": amount, "reason": why}
    return Remedy("refund", params, why, "proposed", basis=basis)


_RUPEE = 100


def voucher_ceiling_paise(settings: dict) -> int:
    """The most a voucher can be before the order's own total is applied: the lower of the
    tenant's hard cap and its auto-approve cap, in whole rupees. Shared with the plain-language
    rules summary (S8.2) so the words cannot drift from what `_voucher` allows."""
    value = min(settings["voucher_auto_approve_max_paise"], settings["voucher_max_paise"])
    return value - value % _RUPEE


def _voucher(
    order_ref: str, order_total_paise: int, settings: dict, why: str, lead: tuple[dict, ...] = ()
) -> Remedy:
    # Never more than the customer paid (voucher_percent of the order total, default 100),
    # never above the tenant's hard cap or its auto-approve cap. The order total is used, not a
    # line total: decide_remedy has no per-item link from the case, so we don't guess one.
    # .get: a pack stored in the DB before voucher_percent existed lacks the key (100 = default).
    percent = settings.get("voucher_percent", 100)
    scaled = percent_of(order_total_paise, percent)
    ceiling = voucher_ceiling_paise(settings)
    value = min(ceiling, scaled)
    value -= value % _RUPEE  # whole rupees, rounded down
    if value < MIN_VOUCHER_PAISE:
        return Remedy(None, {}, "order too small for a voucher; a person decides", "escalate")
    # Which rule set the amount. Both codes when the order total and the cap coincide. The cap
    # figure is the amount actually given (after the round-down), so the line never disagrees
    # with the voucher.
    basis = []
    if scaled <= ceiling:
        basis.append({"code": "voucher_order_total", "params": {"percent": percent}})
    if ceiling <= scaled:
        basis.append({"code": "voucher_cap", "params": {"cap_paise": value}})
    params = {"transaction_id": order_ref, "value_paise": value, "reason": why}
    return Remedy("free_item_voucher", params, why, "proposed", basis=lead + tuple(basis))


def propose_for_case(
    session: Session, ctx: TenantContext, case: Case
) -> tuple[Remedy, uuid.UUID | None]:
    remedy = decide_remedy(session, case)
    record_fallback(session, ctx.tenant_id, case.id, remedy)
    if remedy.action is None:
        return remedy, None
    proposal = create_proposal(
        session,
        ctx.tenant_id,
        case_id=case.id,
        action=remedy.action,
        params=remedy.params,
        reason=f"deterministic rule: {remedy.reason}",
        basis=list(remedy.basis),
    )
    return remedy, proposal.id


def record_fallback(session: Session, tenant_id: uuid.UUID, case_id: uuid.UUID, r: Remedy) -> None:
    """Audit that the customer's pick could not be honoured (option code and action only)."""
    if r.fallback_from is None:
        return
    audit.record(
        session,
        tenant_id,
        actor_type="system",
        actor_id=None,
        event="case.remedy_choice_fallback",
        entity_type="case",
        entity_id=case_id,
        payload={"picked": r.fallback_from, "used": r.action},
    )
