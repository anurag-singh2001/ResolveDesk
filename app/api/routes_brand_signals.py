"""S11.4: GET /growth/brand-signals, repeat-rate readings per brand for HQ.

Scope comes from the caller's membership only. Only hq_owner may read; every other role gets
404 (the feature does not exist for them). An hq_owner limited to some brands sees only those,
and a brand_id outside that scope, or in another tenant (RLS hides it), is a 404. Read-only:
no campaign can be proposed from a brand signal (campaigns stay location-bound).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_clock, not_found, tenant_db
from app.api.routes_growth import require_growth
from app.core.tenancy import TenantContext
from app.modules.growth import brand_signals as bs
from app.modules.growth.signals import data_as_of

router = APIRouter(prefix="/growth", tags=["growth"])

DEFINITION = (
    "Repeat rate per brand: an order is a repeat if the same customer ordered the same brand "
    "in the previous 28 days, at any location. A customer who orders from two brands counts "
    "as a repeat within each brand separately."
)


def require_hq(ctx: TenantContext = Depends(require_growth)) -> TenantContext:
    if ctx.role != "hq_owner":
        raise not_found()
    return ctx


class BrandSignalOut(BaseModel):
    brand_id: uuid.UUID
    name: str
    status: str  # drop | steady | low_volume
    baseline_orders: int
    recent_orders: int
    min_orders: int
    # Rates and drop are null for low_volume: a trend is never shown on too few orders.
    baseline_bp: int | None
    recent_bp: int | None
    drop_bp: int | None
    diagnosis: dict | None  # findings / hypotheses, only for status == drop


class BrandSignalsOut(BaseModel):
    as_of: datetime
    recent_start: datetime
    baseline_start: datetime
    definition: str
    brands: list[BrandSignalOut]


@router.get("/brand-signals")
def brand_signals(
    brand_id: uuid.UUID | None = None,
    ctx: TenantContext = Depends(require_hq),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> BrandSignalsOut:
    as_of = data_as_of(db, ctx.tenant_id, now)
    rows = bs.brand_readings(db, ctx.tenant_id, ctx.brand_ids, as_of)
    if brand_id is not None:
        rows = [r for r in rows if r.brand_id == brand_id]
        if not rows:
            raise not_found()
    out = []
    for r in rows:
        shown = not r.low_volume
        diagnosis = None
        if r.flagged:
            diagnosis = bs.brand_diagnosis(bs.brand_evidence(db, ctx.tenant_id, r)).model_dump()
        out.append(
            BrandSignalOut(
                brand_id=r.brand_id,
                name=r.name,
                status=r.status,
                baseline_orders=r.baseline_n,
                recent_orders=r.recent_n,
                min_orders=r.min_orders,
                baseline_bp=r.baseline_bp if shown else None,
                recent_bp=r.recent_bp if shown else None,
                drop_bp=r.drop_bp if shown else None,
                diagnosis=diagnosis,
            )
        )
    first = rows[0] if rows else None
    return BrandSignalsOut(
        as_of=as_of,
        recent_start=first.recent_start if first else as_of,
        baseline_start=first.baseline_start if first else as_of,
        definition=DEFINITION,
        brands=out,
    )
