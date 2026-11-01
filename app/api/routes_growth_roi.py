"""Offer ROI (S11.3b). Everything here is read only except POST /growth/spend, the one manual
entry (hq_owner, audited). Scope follows the campaign routes: a campaign outside the caller's
locations, or in another tenant (RLS), is a 404. Revenue is aggregate per arm; no customer ids,
names or phones leave this route.
"""

import re
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_clock, not_found, tenant_db
from app.api.routes_growth import require_growth
from app.core import audit
from app.core.models import Campaign, CampaignMember, ManualSpend, PlaybookEntry
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext
from app.modules.growth import campaigns as camp
from app.modules.growth.roi import roi_report

router = APIRouter(prefix="/growth", tags=["growth"])

UNVERIFIED = "entered by hand, not verified"
_CHANNEL = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@router.get("/campaigns/{campaign_id}/roi")
def campaign_roi(
    campaign_id: uuid.UUID,
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> dict:
    try:
        c = camp.load_campaign(db, ctx, campaign_id)
    except camp.NotFound:
        raise not_found() from None
    entry = db.scalar(select(PlaybookEntry).where(PlaybookEntry.campaign_id == c.id))
    settings = effective_settings(db, location_id=c.location_id)
    return roi_report(db, c, settings, now, entry.verdict if entry else None)


class SpendIn(BaseModel):
    channel: str
    amount_paise: int = Field(gt=0, strict=True)
    period_start: date
    period_end: date

    @field_validator("channel")
    @classmethod
    def _channel_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if not _CHANNEL.match(v) or v == "whatsapp":
            raise ValueError("channel must be a short lowercase name, not whatsapp")
        return v


class SpendOut(BaseModel):
    id: uuid.UUID
    channel: str
    amount_paise: int
    period_start: date
    period_end: date
    entered_by: uuid.UUID
    entered_at: datetime
    verification: str = UNVERIFIED


def _spend_out(s: ManualSpend) -> SpendOut:
    return SpendOut(
        id=s.id,
        channel=s.channel,
        amount_paise=s.amount_paise,
        period_start=s.period_start,
        period_end=s.period_end,
        entered_by=s.entered_by,
        entered_at=s.created_at,
    )


def _hq(ctx: TenantContext) -> None:
    if ctx.role != "hq_owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hq_owner only")


@router.post("/spend", status_code=status.HTTP_201_CREATED)
def enter_spend(
    body: SpendIn,
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
) -> SpendOut:
    """The only write in the ROI feature: a typed-in spend amount, kept as entered."""
    _hq(ctx)
    if body.period_end < body.period_start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "period_end is before start")
    row = ManualSpend(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        channel=body.channel,
        amount_paise=body.amount_paise,
        period_start=body.period_start,
        period_end=body.period_end,
        entered_by=ctx.user_id,
    )
    db.add(row)
    audit.record(
        db,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="growth.spend_entered",
        entity_type="growth_manual_spend",
        entity_id=row.id,
        payload={
            "channel": row.channel,
            "amount_paise": row.amount_paise,
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
        },
    )
    db.flush()
    db.refresh(row)
    return _spend_out(row)


@router.get("/channel-mix")
def channel_mix(
    ctx: TenantContext = Depends(require_growth), db: Session = Depends(tenant_db)
) -> dict:
    """WhatsApp spend and sends from in-scope campaigns (spend is the budget cap, an upper
    bound), plus hand-entered aggregator spend for hq_owner only (it belongs to no location)."""
    scoped = [c for c in db.scalars(select(Campaign)) if camp.in_scope(ctx, c.location_id)]
    sent = [c for c in scoped if c.status in ("sent", "measured")]
    budget = sum(c.budget_paise for c in sent)
    sends = {"treatment": 0, "succeeded": 0}
    if sent:
        rows = db.execute(
            select(CampaignMember.send_status).where(
                CampaignMember.campaign_id.in_([c.id for c in sent]),
                CampaignMember.arm == "treatment",
            )
        )
        for (state,) in rows:
            sends["treatment"] += 1
            sends["succeeded"] += 1 if state == "succeeded" else 0
    manual: list[SpendOut] = []
    if ctx.role == "hq_owner":
        manual = [
            _spend_out(s)
            for s in db.scalars(
                select(ManualSpend).order_by(ManualSpend.period_start.desc(), ManualSpend.id)
            )
        ]
    return {
        "whatsapp": {
            "campaigns": len(sent),
            "budget_cap_paise": budget,
            "treatment_sends": sends["treatment"],
            "succeeded_sends": sends["succeeded"],
            "note": "Budget cap is an upper bound; redemptions are not tracked.",
        },
        "manual_spend": [m.model_dump(mode="json") for m in manual],
        "manual_spend_note": UNVERIFIED,
    }
