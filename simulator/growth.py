"""Simulator hook for E8.3: orders placed after a campaign, so a verdict has something to
measure. Deterministic per (seed, customer); the treatment and holdout arms get separate
repeat rates, which is how a test plants "the offer worked" or "it did nothing"."""

import hashlib
import uuid
from datetime import timedelta

from sqlalchemy import Engine, select

from app.core.db import tenant_session
from app.core.models import Campaign, CampaignMember, LocationBrand, Transaction


def _roll_bp(seed: int, customer_id: uuid.UUID) -> int:
    digest = hashlib.sha256(f"{seed}:{customer_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 10000


def simulate_post_campaign_orders(
    engine: Engine,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    treatment_rate_bp: int,
    holdout_rate_bp: int,
    seed: int = 42,
) -> int:
    """Insert one order inside the campaign window for each member who 'comes back'. Returns
    the number of orders added. Dev/test only: it writes orders the way a source system would."""
    with tenant_session(tenant_id, engine) as s:
        campaign = s.get(Campaign, campaign_id)
        if campaign is None or campaign.sent_at is None:
            raise ValueError("campaign has not been sent")
        brand_id = s.scalar(
            select(LocationBrand.brand_id)
            .where(LocationBrand.location_id == campaign.location_id)
            .order_by(LocationBrand.brand_id)
        )
        added = 0
        for m in s.scalars(select(CampaignMember).where(CampaignMember.campaign_id == campaign.id)):
            rate = treatment_rate_bp if m.arm == "treatment" else holdout_rate_bp
            if _roll_bp(seed, m.customer_id) >= rate:
                continue
            offset = timedelta(hours=1 + _roll_bp(seed + 1, m.customer_id) % 24 * 13)
            s.add(
                Transaction(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    customer_id=m.customer_id,
                    brand_id=brand_id,
                    location_id=campaign.location_id,
                    source="sim_growth",
                    external_ref=f"SIM-{campaign.id.hex[:12]}-{m.customer_id.hex[:12]}",
                    placed_at=campaign.sent_at + offset,
                    total_paise=25000,
                    status="completed",
                )
            )
            added += 1
        return added
