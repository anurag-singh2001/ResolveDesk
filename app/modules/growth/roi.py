"""S11.3b: offer ROI against the holdout. Read only, integer paise, nothing stored.

Per arm: people assigned, people who ordered, orders and revenue in the window at the campaign's
location (cancelled orders excluded). Intention to treat: every assigned person stays in their arm
whatever happened to the send, so failed and unknown sends are inside the treatment numbers.

Incremental revenue = (treated revenue per customer - held-out revenue per customer) x treated
customers, done as one integer division. Cost is an UPPER BOUND: the budget cap (offer x treated
people) is charged in full because redemptions are not tracked, plus the estimated message cost
for each send that succeeded. The existing verdict gates the headline: when it is inconclusive
(or the window is still open) no ROI is returned as a result.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Campaign, CampaignMember, Transaction
from app.modules.growth.verdict import MIN_ARM_N, compute_verdict

SEND_STATES = ("pending", "submitted", "processing", "succeeded", "failed", "unknown", "skipped")
DEFAULT_MESSAGE_COST_PAISE = 86  # estimate
DEFAULT_MARGIN_BP = 6000  # estimate
TARGET_LIFT_BP = 500  # "detect a 5-point lift"
RECOMMEND_SMALL_AUDIENCE = 1000
RECOMMENDED_HOLDOUT_PERCENT = 20
REVENUE_NOTE = "Order-rate result is tested, revenue is indicative."


@dataclass(frozen=True)
class Arm:
    customers: int = 0
    ordered: int = 0
    orders: int = 0
    revenue_paise: int = 0


def div_round(num: int, den: int) -> int:
    """Integer division rounded half away from zero. No floats."""
    if den <= 0:
        raise ValueError("den must be positive")
    q, r = divmod(abs(num), den)
    if 2 * r >= den:
        q += 1
    return q if num >= 0 else -q


def incremental_revenue_paise(treated: Arm, held_out: Arm) -> int:
    """(t_rev / t_n - h_rev / h_n) * t_n  ==  (t_rev * h_n - h_rev * t_n) / h_n."""
    if treated.customers <= 0 or held_out.customers <= 0:
        return 0
    return div_round(
        treated.revenue_paise * held_out.customers - held_out.revenue_paise * treated.customers,
        held_out.customers,
    )


def gross_cost_paise(budget_paise: int, succeeded_sends: int, message_cost_paise: int) -> int:
    return budget_paise + message_cost_paise * succeeded_sends


def ratio_bp(net_paise: int, cost_paise: int) -> int | None:
    """Net / cost in basis points (integer), None with no cost."""
    return div_round(net_paise * 10000, cost_paise) if cost_paise > 0 else None


def people_needed_per_arm(holdout_rate_bp: int, lift_bp: int = TARGET_LIFT_BP) -> int:
    """People per arm for ~80% power at 95% (two-sided) to see `lift_bp`, from the held-out
    rate. A planning figure only (floats inside, an integer out, nothing stored)."""
    p1 = min(max(holdout_rate_bp, 0), 10000 - lift_bp) / 10000
    p2 = p1 + lift_bp / 10000
    pbar = (p1 + p2) / 2
    n = 2 * (1.96 + 0.84) ** 2 * pbar * (1 - pbar) / (lift_bp / 10000) ** 2
    return max(MIN_ARM_N, math.ceil(n))


def detectable_lift_bp(treatment_n: int, holdout_n: int) -> int | None:
    """Smallest lift (basis points) this split could reliably see at 80% power, worst case
    rate 50%. None when an arm is empty."""
    if treatment_n <= 0 or holdout_n <= 0:
        return None
    return math.ceil(2.8 * math.sqrt(0.25 * (1 / treatment_n + 1 / holdout_n)) * 10000)


def holdout_advice(treatment_n: int, holdout_n: int, holdout_percent: int) -> dict:
    audience = treatment_n + holdout_n
    recommend = (
        RECOMMENDED_HOLDOUT_PERCENT
        if audience < RECOMMEND_SMALL_AUDIENCE and holdout_percent < RECOMMENDED_HOLDOUT_PERCENT
        else None
    )
    return {
        "holdout_percent": holdout_percent,
        "audience_n": audience,
        "detectable_lift_bp": detectable_lift_bp(treatment_n, holdout_n),
        "recommended_holdout_percent": recommend,
        "note": "Estimate. A larger holdout sees smaller lifts; the default stays "
        f"{holdout_percent} percent.",
    }


def arm_tallies(session: Session, campaign: Campaign) -> tuple[dict[str, Arm], dict[str, int]]:
    """({arm: Arm}, {send state: treatment members}). Read only. Before the campaign is sent
    there is no window, so orders and revenue are zero."""
    sends = dict.fromkeys(SEND_STATES, 0)
    acc = {"treatment": [0, 0, 0, 0], "holdout": [0, 0, 0, 0]}
    if campaign.sent_at is None:
        rows = session.execute(
            select(CampaignMember.arm, CampaignMember.send_status).where(
                CampaignMember.campaign_id == campaign.id
            )
        )
        for arm, state in rows:
            acc[arm][0] += 1
            if arm == "treatment":
                sends[state] += 1
        return {k: Arm(*v) for k, v in acc.items()}, sends
    start = campaign.sent_at
    end = start + timedelta(days=int(campaign.params["window_days"]))
    window = (
        Transaction.tenant_id == campaign.tenant_id,
        Transaction.customer_id == CampaignMember.customer_id,
        Transaction.location_id == campaign.location_id,
        Transaction.status != "cancelled",
        Transaction.placed_at >= start,
        Transaction.placed_at < end,
    )
    n_orders = (
        select(func.count()).select_from(Transaction).where(*window).correlate(CampaignMember)
    ).scalar_subquery()
    revenue = (
        select(func.coalesce(func.sum(Transaction.total_paise), 0))
        .where(*window)
        .correlate(CampaignMember)
    ).scalar_subquery()
    for arm, state, n, rev in session.execute(
        select(CampaignMember.arm, CampaignMember.send_status, n_orders, revenue).where(
            CampaignMember.campaign_id == campaign.id
        )
    ):
        a = acc[arm]
        a[0] += 1
        a[1] += 1 if n else 0
        a[2] += n
        a[3] += int(rev)
        if arm == "treatment":
            sends[state] += 1
    return {k: Arm(*v) for k, v in acc.items()}, sends


def _int_setting(settings: dict, key: str, default: int) -> int:
    v = settings.get(key, default)
    return v if type(v) is int and v >= 0 else default


def _arm_out(a: Arm) -> dict:
    return {
        "customers": a.customers,
        "ordered": a.ordered,
        "orders": a.orders,
        "revenue_paise": a.revenue_paise,
    }


def roi_report(
    session: Session,
    campaign: Campaign,
    settings: dict,
    now: datetime,
    stored_verdict: str | None,
) -> dict:
    arms, sends = arm_tallies(session, campaign)
    t, h = arms["treatment"], arms["holdout"]
    message_cost = _int_setting(settings, "growth_message_cost_paise", DEFAULT_MESSAGE_COST_PAISE)
    margin_bp = min(_int_setting(settings, "growth_gross_margin_bp", DEFAULT_MARGIN_BP), 10000)
    basis = "margin" if settings.get("growth_roi_basis") == "margin" else "revenue"
    window_days = int(campaign.params["window_days"])
    window_end = campaign.sent_at + timedelta(days=window_days) if campaign.sent_at else None
    window_over = window_end is not None and now >= window_end
    verdict = (
        stored_verdict or compute_verdict(t.customers, t.ordered, h.customers, h.ordered).verdict
    )
    succeeded = sends["succeeded"]
    cost = gross_cost_paise(campaign.budget_paise, succeeded, message_cost)
    incremental = incremental_revenue_paise(t, h)
    value = div_round(incremental * margin_bp, 10000) if basis == "margin" else incremental
    net = value - cost
    if not window_over:
        gate = "window_open"
    elif verdict == "inconclusive":
        gate = "inconclusive"
    else:
        gate = "ok"
    headline = (
        {"basis": basis, "value_paise": value, "net_paise": net, "ratio_bp": ratio_bp(net, cost)}
        if gate == "ok"
        else None
    )
    h_rate = div_round(h.ordered * 10000, h.customers) if h.customers else 0
    return {
        "campaign_id": str(campaign.id),
        "status": campaign.status,
        "verdict": verdict if window_over else None,
        "window_over": window_over,
        "arms": {"treatment": _arm_out(t), "holdout": _arm_out(h)},
        "send_states": sends,
        "incremental_revenue_paise": incremental if gate == "ok" else None,
        "cost": {
            "offer_budget_paise": campaign.budget_paise,
            "message_cost_each_paise": message_cost,
            "message_cost_paise": message_cost * succeeded,
            "succeeded_sends": succeeded,
            "gross_cost_paise": cost,
            "note": "Upper bound: the budget cap is charged in full because redemptions are not "
            "tracked. Message cost is an estimate.",
        },
        "gross_margin_bp": margin_bp,
        "gate": gate,
        "headline": headline,
        "message": "Not enough people to tell" if gate == "inconclusive" else None,
        "people_needed_per_arm": people_needed_per_arm(h_rate) if gate == "inconclusive" else None,
        "revenue_note": REVENUE_NOTE,
        "estimates": ["growth_message_cost_paise", "growth_gross_margin_bp"],
        "holdout_advice": holdout_advice(
            int(campaign.params["treatment_n"]),
            int(campaign.params["holdout_n"]),
            int(campaign.params.get("holdout_percent", 0)),
        ),
    }
