"""E8.2: audience, campaign proposal bound to a payload hash, dual approval.

A campaign is an ActionProposal-style record (it does not reuse `action_proposals`, whose rows
hang off a support case). Its hash covers the signal, location, params AND the exact audience,
so an approval can never be replayed against a different offer or a different set of people
(hard rule 6). Approvals expire. Two different staff users must approve, at least one of them
an hq_owner. Nothing is sent from here: sending is app/modules/growth/executor.py, after both
approvals, outside any open transaction (hard rule 5).
"""

import hashlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import Campaign, CampaignApproval, CampaignMember, Signal
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext
from app.engine.proposals import ProposalError, canonical_json

ACTION = "win_back_campaign"
TEMPLATE = "winback_offer"
LAPSED_DAYS = 28  # no order at the location in this long before the signal window ended
FREQUENCY_CAP_DAYS = 30  # nobody is in two campaigns within this long
PROPOSAL_TTL = timedelta(hours=48)
APPROVAL_TTL = timedelta(hours=24)
DEFAULT_OFFER_PAISE = 5000
DEFAULT_WINDOW_DAYS = 14
_NS = uuid.UUID("0b0c5d4e-6d66-4a6e-9a0a-3f6f9b1d7a11")


class GrowthError(Exception):
    pass


class NotFound(GrowthError):  # also for out of scope: existence isn't confirmed (rule 8)
    pass


class Forbidden(GrowthError):
    pass


class AlreadyDecided(GrowthError):
    pass


class NotEligible(GrowthError):
    pass


class Expired(GrowthError):
    pass


def lapsed_audience(
    session: Session, tenant_id: uuid.UUID, location_id: uuid.UUID, as_of: datetime
) -> list[tuple[uuid.UUID, str]]:
    """(customer_id, phone) of lapsed customers of a location, ordered by id: ordered here
    before the cut-off but not since; with a phone; marketing consent on WhatsApp (no consent
    row means no consent); not already in a campaign inside the frequency cap. One customer per
    phone, since real data has duplicate numbers and nobody should be messaged twice."""
    cut = as_of - timedelta(days=LAPSED_DAYS)
    rows = session.execute(
        text(
            """
            SELECT c.id, c.phone FROM customers c
            WHERE c.tenant_id = :tid AND c.phone IS NOT NULL AND c.phone <> ''
              AND EXISTS (SELECT 1 FROM transactions t WHERE t.tenant_id = :tid
                  AND t.customer_id = c.id AND t.location_id = :loc
                  AND t.status <> 'cancelled' AND t.placed_at < :cut)
              AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.tenant_id = :tid
                  AND t.customer_id = c.id AND t.location_id = :loc
                  AND t.status <> 'cancelled' AND t.placed_at >= :cut)
              AND EXISTS (SELECT 1 FROM consents k WHERE k.tenant_id = :tid
                  AND k.customer_id = c.id AND k.channel = 'whatsapp'
                  AND k.purpose = 'marketing' AND k.granted)
              AND NOT EXISTS (SELECT 1 FROM campaign_members m WHERE m.tenant_id = :tid
                  AND m.customer_id = c.id AND m.created_at >= :capcut)
            ORDER BY c.id
            """
        ),
        {
            "tid": tenant_id,
            "loc": location_id,
            "cut": cut,
            "capcut": as_of - timedelta(days=FREQUENCY_CAP_DAYS),
        },
    )
    seen_phones: set[str] = set()
    out = []
    for cid, phone in rows:
        if phone not in seen_phones:
            seen_phones.add(phone)
            out.append((cid, phone))
    return out


def split_audience(
    customer_ids: list[uuid.UUID], seed: str, holdout_percent: int
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """(treatment, holdout), each sorted. Deterministic for the same ids and seed whatever the
    input order: customers are ranked by sha256(seed:id) and the first k are held out. At least
    one person is held out and at least one treated."""
    ranked = sorted(customer_ids, key=lambda i: hashlib.sha256(f"{seed}:{i}".encode()).hexdigest())
    k = min(len(ranked) - 1, max(1, round(len(ranked) * holdout_percent / 100)))
    return sorted(ranked[k:]), sorted(ranked[:k])


def audience_sha(treatment: list[uuid.UUID], holdout: list[uuid.UUID]) -> str:
    material = {"treatment": sorted(map(str, treatment)), "holdout": sorted(map(str, holdout))}
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()


def compute_hash(signal_id: uuid.UUID, location_id: uuid.UUID, params: dict, audience: str) -> str:
    material = {
        "action": ACTION,
        "signal_id": str(signal_id),
        "location_id": str(location_id),
        "params": params,
        "audience_sha": audience,
    }
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()


def members_of(session: Session, campaign: Campaign) -> list[CampaignMember]:
    return list(
        session.scalars(
            select(CampaignMember)
            .where(CampaignMember.campaign_id == campaign.id)
            .order_by(CampaignMember.customer_id)
        )
    )


def hash_is_intact(session: Session, campaign: Campaign) -> bool:
    """Recompute the hash from what is actually stored (params + members)."""
    ms = members_of(session, campaign)
    treatment = [m.customer_id for m in ms if m.arm == "treatment"]
    holdout = [m.customer_id for m in ms if m.arm == "holdout"]
    sha = audience_sha(treatment, holdout)
    return sha == campaign.audience_sha and campaign.payload_hash == compute_hash(
        campaign.signal_id, campaign.location_id, campaign.params, sha
    )


def in_scope(ctx: TenantContext, location_id: uuid.UUID) -> bool:
    return ctx.is_staff and (ctx.role == "hq_owner" or ctx.can_see_location(location_id))


def load_signal(session: Session, ctx: TenantContext, signal_id: uuid.UUID) -> Signal:
    signal = session.get(Signal, signal_id)  # RLS: other tenants' signals don't exist
    if signal is None or not in_scope(ctx, signal.location_id):
        raise NotFound("signal not found")
    return signal


def load_campaign(session: Session, ctx: TenantContext, campaign_id: uuid.UUID) -> Campaign:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None or not in_scope(ctx, campaign.location_id):
        raise NotFound("campaign not found")
    return campaign


def propose(
    session: Session,
    ctx: TenantContext,
    signal_id: uuid.UUID,
    now: datetime,
    offer_paise: int = DEFAULT_OFFER_PAISE,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Campaign:
    """Build the audience, split it, and store a campaign awaiting approval. Idempotent: one
    campaign per signal, so re-running returns the first one (same audience, same hash)."""
    signal = load_signal(session, ctx, signal_id)
    existing = session.scalar(select(Campaign).where(Campaign.signal_id == signal.id))
    if existing is not None:
        return existing
    if type(offer_paise) is not int or offer_paise <= 0:
        raise ProposalError("offer_paise must be a positive integer")
    if type(window_days) is not int or not 1 <= window_days <= 60:
        raise ProposalError("window_days must be 1..60")
    settings = effective_settings(session, location_id=signal.location_id)
    pct = settings["growth_holdout_percent"]
    audience = lapsed_audience(session, ctx.tenant_id, signal.location_id, signal.recent_end)
    if len(audience) < 2:
        raise ProposalError("not enough eligible lapsed customers to run a campaign with a holdout")
    treatment, holdout = split_audience([c for c, _ in audience], str(signal.id), pct)
    budget = offer_paise * len(treatment)
    cap = settings["growth_campaign_budget_paise"]
    if budget > cap:
        raise ProposalError(f"campaign budget {budget} paise is above the limit of {cap} paise")
    params = {
        "offer_paise": offer_paise,
        "window_days": window_days,
        "template": TEMPLATE,
        "holdout_percent": pct,
        "split_seed": str(signal.id),
        "lapsed_days": LAPSED_DAYS,
        "treatment_n": len(treatment),
        "holdout_n": len(holdout),
    }
    sha = audience_sha(treatment, holdout)
    campaign = Campaign(
        id=uuid.uuid5(_NS, f"{ctx.tenant_id}:{signal.id}"),  # same signal, same campaign id
        tenant_id=ctx.tenant_id,
        signal_id=signal.id,
        location_id=signal.location_id,
        created_by=ctx.user_id,
        params=params,
        audience_sha=sha,
        payload_hash=compute_hash(signal.id, signal.location_id, params, sha),
        budget_paise=budget,
        status="pending_approval",
        expires_at=now + PROPOSAL_TTL,
    )
    try:
        with session.begin_nested():
            session.add(campaign)
            session.flush()
            for arm, ids in (("treatment", treatment), ("holdout", holdout)):
                for customer_id in ids:
                    session.add(
                        CampaignMember(
                            id=uuid.uuid4(),
                            tenant_id=ctx.tenant_id,
                            campaign_id=campaign.id,
                            customer_id=customer_id,
                            arm=arm,
                            # One stable key per (campaign, customer): reruns reuse it.
                            idempotency_key=f"C-{campaign.id}:{customer_id}:send:1",
                        )
                    )
            signal.status = "actioned"
    except IntegrityError:  # a parallel request created it first
        return session.scalar(select(Campaign).where(Campaign.signal_id == signal.id))
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="campaign.proposed",
        entity_type="campaign",
        entity_id=campaign.id,
        payload={"payload_hash": campaign.payload_hash, "budget_paise": budget},
    )
    return campaign


def valid_approvals(
    campaign: Campaign, approvals: list[CampaignApproval], now: datetime
) -> list[CampaignApproval]:
    """Approvals that count now: for exactly this payload, approving, unexpired."""
    return [
        a
        for a in approvals
        if a.decision == "approved"
        and a.payload_hash == campaign.payload_hash
        and a.expires_at > now
    ]


def dual_approved(valid: list[CampaignApproval]) -> bool:
    """Two different staff users, at least one hq_owner."""
    users = {a.decided_by for a in valid}
    return len(users) >= 2 and any(a.role == "hq_owner" for a in valid)


def approvals_of(session: Session, campaign: Campaign) -> list[CampaignApproval]:
    return list(
        session.scalars(
            select(CampaignApproval)
            .where(CampaignApproval.campaign_id == campaign.id)
            .order_by(CampaignApproval.decided_at, CampaignApproval.id)
        )
    )


def decide(
    session: Session,
    ctx: TenantContext,
    campaign_id: uuid.UUID,
    decision: str,
    now: datetime,
) -> tuple[CampaignApproval, bool]:
    """Record one staff member's decision. Returns (approval, fully approved). When the second
    qualifying approval lands the campaign becomes `approved`; sending happens afterwards, in
    the executor, once this transaction has committed."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    campaign = load_campaign(session, ctx, campaign_id)
    if campaign.status != "pending_approval":
        raise AlreadyDecided(f"campaign is {campaign.status}")
    if now >= campaign.expires_at:
        raise Expired("campaign proposal has expired")
    if not hash_is_intact(session, campaign):
        raise NotEligible("campaign no longer matches its payload hash")
    approval = CampaignApproval(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        campaign_id=campaign.id,
        payload_hash=campaign.payload_hash,  # exactly what this approver saw
        decision=decision,
        decided_by=ctx.user_id,
        role=ctx.role,
        decided_at=now,
        expires_at=min(now + APPROVAL_TTL, campaign.expires_at),
    )
    try:
        with session.begin_nested():
            session.add(approval)
    except IntegrityError:  # unique (campaign, user): approving twice never counts twice
        raise AlreadyDecided("you have already decided this campaign") from None
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event=f"campaign.{decision}",
        entity_type="campaign",
        entity_id=campaign.id,
        payload={"payload_hash": campaign.payload_hash, "role": ctx.role},
    )
    if decision == "rejected":
        campaign.status = "rejected"
        return approval, False
    ready = dual_approved(valid_approvals(campaign, approvals_of(session, campaign), now))
    if ready:
        campaign.status = "approved"
    return approval, ready
