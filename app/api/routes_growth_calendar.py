"""Campaign calendar (S11.3a): GET /growth/calendar. Read-only; there is no write path here.

Scope comes from the caller's membership: a campaign is listed only if its location is in scope
and, for a brand-limited membership, the location serves one of its brands. A location or brand
id sent by the client can only narrow that, and an id outside the scope (or in another tenant,
which RLS hides) is a 404. Counts only: no customer ids, names or phones leave this route.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_clock, not_found, tenant_db
from app.api.routes_growth import require_growth
from app.core.models import Brand, Campaign, CampaignMember, Location, LocationBrand
from app.core.tenancy import TenantContext
from app.modules.growth.calendar import (
    SEND_STATES,
    CalendarItem,
    warning_counts,
    window_days_of,
    window_of,
)

router = APIRouter(prefix="/growth", tags=["growth"])


class CalendarBrand(BaseModel):
    id: uuid.UUID
    name: str


class CalendarCampaign(BaseModel):
    id: uuid.UUID
    status: str
    location_id: uuid.UUID
    location_name: str
    brands: list[CalendarBrand]
    audience_n: int  # treatment + holdout
    treatment_n: int
    holdout_n: int
    budget_paise: int
    start: datetime
    window_end: datetime
    window_days: int
    send_counts: dict[str, int]  # treatment members per send state, every state kept apart
    overlap_customers: int
    frequency_cap_customers: int


class CalendarResponse(BaseModel):
    as_of: datetime
    campaigns: list[CalendarCampaign]


@router.get("/calendar")
def calendar(
    location_id: uuid.UUID | None = None,
    brand_id: uuid.UUID | None = None,
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> CalendarResponse:
    locations = {
        loc.id: loc
        for loc in db.scalars(select(Location).order_by(Location.slug))
        if ctx.can_see_location(loc.id)
    }
    brands = {
        b.id: b
        for b in db.scalars(select(Brand).order_by(Brand.slug))
        if not ctx.brand_ids or b.id in ctx.brand_ids
    }
    if location_id is not None and location_id not in locations:
        raise not_found()
    if brand_id is not None and brand_id not in brands:
        raise not_found()
    served: dict[uuid.UUID, list[Brand]] = defaultdict(list)
    for lb in db.scalars(select(LocationBrand)):
        if lb.brand_id in brands:
            served[lb.location_id].append(brands[lb.brand_id])

    def listed(c: Campaign) -> bool:
        if c.location_id not in locations:
            return False
        # A brand-limited caller sees only locations that serve one of their brands.
        return not ctx.brand_ids or bool(served.get(c.location_id))

    campaigns = [c for c in db.scalars(select(Campaign).order_by(Campaign.id)) if listed(c)]

    treated: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    sends: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: dict.fromkeys(SEND_STATES, 0))
    members = select(
        CampaignMember.campaign_id, CampaignMember.customer_id, CampaignMember.send_status
    ).where(
        CampaignMember.campaign_id.in_([c.id for c in campaigns]),
        CampaignMember.arm == "treatment",
    )
    for cid, customer, send_status in db.execute(members):
        treated[cid].add(customer)
        sends[cid][send_status] += 1

    items = []
    for c in campaigns:
        start, end = window_of(c.sent_at, c.expires_at, window_days_of(c.params))
        items.append(
            CalendarItem(c.id, c.status, start, end, c.created_at, frozenset(treated[c.id]))
        )
    warnings = warning_counts(items, now)

    out = []
    for c, item in zip(campaigns, items, strict=True):
        shown = sorted(served.get(c.location_id, []), key=lambda b: b.slug)
        if brand_id is not None and all(b.id != brand_id for b in shown):
            continue
        if location_id is not None and c.location_id != location_id:
            continue
        overlap, cap = warnings[c.id]
        out.append(
            CalendarCampaign(
                id=c.id,
                status=c.status,
                location_id=c.location_id,
                location_name=locations[c.location_id].name,
                brands=[CalendarBrand(id=b.id, name=b.name) for b in shown],
                audience_n=int(c.params["treatment_n"]) + int(c.params["holdout_n"]),
                treatment_n=int(c.params["treatment_n"]),
                holdout_n=int(c.params["holdout_n"]),
                budget_paise=c.budget_paise,
                start=item.start,
                window_end=item.end,
                window_days=window_days_of(c.params),
                send_counts=dict(sends[c.id]),
                overlap_customers=overlap,
                frequency_cap_customers=cap,
            )
        )
    out.sort(key=lambda x: (x.start, str(x.id)))
    return CalendarResponse(as_of=now, campaigns=out)
