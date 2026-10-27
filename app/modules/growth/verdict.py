"""E8.3: the honest verdict, and the playbook entry.

After the campaign window, compare the share of treatment members who ordered again at the
location with the same share among the held-out members. Everyone assigned counts (intention
to treat): a failed send is part of the campaign's result, not a reason to drop the customer,
and dropping them would flatter the numbers.

The verdict is `worked` or `did_not_work` only when each arm is big enough (MIN_ARM_N) and the
difference is significant (|z| >= 1.96, two-sided 95%). Otherwise `inconclusive`, and the note
says why. One playbook row per campaign, so asking twice returns the first answer.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import Campaign, CampaignMember, PlaybookEntry, Transaction
from app.core.money import format_inr
from app.core.tenancy import TenantContext
from app.modules.growth.campaigns import GrowthError, load_campaign

MIN_ARM_N = 20
Z_SIGNIFICANT_X100 = 196


class NotReady(GrowthError):
    pass


@dataclass(frozen=True)
class Verdict:
    verdict: str  # worked | did_not_work | inconclusive
    uplift_bp: int
    z_x100: int
    note: str


def compute_verdict(t_n: int, t_hits: int, h_n: int, h_hits: int) -> Verdict:
    t_bp = round(t_hits * 10000 / t_n) if t_n else 0
    h_bp = round(h_hits * 10000 / h_n) if h_n else 0
    uplift = t_bp - h_bp
    if t_n < MIN_ARM_N or h_n < MIN_ARM_N:
        return Verdict(
            "inconclusive",
            uplift,
            0,
            f"Too few people to tell: {t_n} treated and {h_n} held out (need at least "
            f"{MIN_ARM_N} in each). The raw difference of {uplift / 100:+.1f} points is "
            "not evidence either way.",
        )
    pooled = (t_hits + h_hits) / (t_n + h_n)
    se = math.sqrt(pooled * (1 - pooled) * (1 / t_n + 1 / h_n))
    z_x100 = round((t_hits / t_n - h_hits / h_n) / se * 100) if se else 0
    if abs(z_x100) < Z_SIGNIFICANT_X100:
        return Verdict(
            "inconclusive",
            uplift,
            z_x100,
            f"Treated repeat rate {t_bp / 100:.1f}% vs held-out {h_bp / 100:.1f}% "
            f"({uplift / 100:+.1f} points) is within what chance produces (z={z_x100 / 100:.2f}).",
        )
    word = "worked" if z_x100 > 0 else "did_not_work"
    return Verdict(
        word,
        uplift,
        z_x100,
        f"Treated repeat rate {t_bp / 100:.1f}% vs held-out {h_bp / 100:.1f}% "
        f"({uplift / 100:+.1f} points), significant at 95% (z={z_x100 / 100:.2f}). "
        f"Based on {t_n} treated and {h_n} held out; the true effect could be smaller or larger.",
    )


def _lesson(v: Verdict, detail: str) -> str:
    return {
        "worked": f"The win-back offer lifted repeat orders. {detail}",
        "did_not_work": "The win-back offer did not bring customers back; look for the cause "
        f"instead. {detail}",
        "inconclusive": "No conclusion yet: use a larger audience or a longer window before "
        f"repeating. {detail}",
    }[v.verdict].strip()


def measure(
    session: Session, ctx: TenantContext, campaign_id: uuid.UUID, now: datetime
) -> PlaybookEntry:
    """Compute the verdict and write the playbook entry (idempotent)."""
    campaign = load_campaign(session, ctx, campaign_id)
    entry = session.scalar(select(PlaybookEntry).where(PlaybookEntry.campaign_id == campaign.id))
    if entry is not None:
        return entry
    if campaign.status != "sent" or campaign.sent_at is None:
        raise NotReady(f"campaign is {campaign.status}: nothing has been sent to measure")
    start = campaign.sent_at
    end = start + timedelta(days=campaign.params["window_days"])
    if now < end:
        raise NotReady(f"measurement window is open until {end.isoformat()}")
    ordered = (
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.tenant_id == campaign.tenant_id,
            Transaction.customer_id == CampaignMember.customer_id,
            Transaction.location_id == campaign.location_id,
            Transaction.status != "cancelled",
            Transaction.placed_at >= start,
            Transaction.placed_at < end,
        )
        .correlate(CampaignMember)
        .scalar_subquery()
    )
    tally: dict[str, list[int]] = {"treatment": [0, 0], "holdout": [0, 0]}
    for arm, n_orders in session.execute(
        select(CampaignMember.arm, ordered).where(CampaignMember.campaign_id == campaign.id)
    ):
        tally[arm][0] += 1
        tally[arm][1] += 1 if n_orders else 0
    (t_n, t_hits), (h_n, h_hits) = tally["treatment"], tally["holdout"]
    v = compute_verdict(t_n, t_hits, h_n, h_hits)
    entry = PlaybookEntry(
        id=uuid.uuid4(),
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.id,
        location_id=campaign.location_id,
        verdict=v.verdict,
        treatment_n=t_n,
        treatment_repeat=t_hits,
        holdout_n=h_n,
        holdout_repeat=h_hits,
        uplift_bp=v.uplift_bp,
        confidence_note=v.note,
        lesson=_lesson(
            v,
            f"(offer {format_inr(campaign.params['offer_paise'])}, "
            f"{campaign.params['window_days']}-day window)",
        ),
    )
    try:
        with session.begin_nested():
            session.add(entry)
    except IntegrityError:  # a parallel request wrote it first
        return session.scalar(select(PlaybookEntry).where(PlaybookEntry.campaign_id == campaign.id))
    campaign.status = "measured"
    audit.record(
        session,
        campaign.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="campaign.measured",
        entity_type="campaign",
        entity_id=campaign.id,
        payload={"verdict": v.verdict, "uplift_bp": v.uplift_bp},
    )
    return entry


def campaign_of(session: Session, entry: PlaybookEntry) -> Campaign:
    return session.get(Campaign, entry.campaign_id)
