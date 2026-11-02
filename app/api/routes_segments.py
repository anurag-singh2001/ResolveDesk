"""Customer segments and cohorts (S11.2): read-only aggregates under /insights.

Scope follows /insights/metrics: it comes from the caller's membership; a client-supplied
location or brand id can only narrow it, and an id outside the scope (or in another tenant,
which RLS hides) is a 404. Counts only: no customer id, name or phone is ever returned. Not
behind the `growth` feature flag: nothing here sends or proposes anything, so it works the same
for every tenant (the audience that *can* be messaged is shown as `contactable_whatsapp`).
`small_cell_min` (a setting) hides small cells from every role but hq_owner.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_clock, not_found, tenant_db
from app.api.routes_insights import require_metrics
from app.core.models import Brand, Location
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext
from app.modules.growth import segments as seg
from app.modules.growth.signals import data_as_of

router = APIRouter(prefix="/insights", tags=["insights"])


class SegmentsResponse(BaseModel):
    as_of: datetime
    lapsed_days: int
    new_days: int
    small_cell_min: int
    cells_hidden_below_min: bool  # true for roles that do not see small cells
    groups: list[seg.SegmentGroup]


class CohortsResponse(BaseModel):
    as_of: datetime
    small_cell_min: int
    cells_hidden_below_min: bool
    groups: list[seg.CohortGroup]


def _scope(db: Session, ctx: TenantContext, location_id, brand_id):
    visible = [
        loc.id
        for loc in db.scalars(select(Location).order_by(Location.slug))
        if ctx.can_see_location(loc.id)
    ]
    if location_id is not None:
        visible = [i for i in visible if i == location_id]
        if not visible:
            raise not_found()
    brands = [
        (b.id, b.name)
        for b in db.scalars(select(Brand).order_by(Brand.slug))
        if not ctx.brand_ids or b.id in ctx.brand_ids
    ]
    if brand_id is not None:
        brands = [b for b in brands if b[0] == brand_id]
        if not brands:
            raise not_found()
    return visible, brands, brand_id is not None or bool(ctx.brand_ids)


@router.get("/segments")
def segments(
    location_id: uuid.UUID | None = None,
    brand_id: uuid.UUID | None = None,
    ctx: TenantContext = Depends(require_metrics),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> SegmentsResponse:
    locs, brands, narrowed = _scope(db, ctx, location_id, brand_id)
    cfg = seg.SegmentSettings.of(effective_settings(db))
    as_of = data_as_of(db, ctx.tenant_id, now)
    hide = ctx.role != "hq_owner"
    return SegmentsResponse(
        as_of=as_of,
        lapsed_days=cfg.lapsed_days,
        new_days=cfg.new_days,
        small_cell_min=cfg.small_cell_min,
        cells_hidden_below_min=hide,
        groups=seg.segment_groups(db, ctx.tenant_id, locs, brands, narrowed, as_of, cfg, hide),
    )


@router.get("/cohorts")
def cohorts(
    location_id: uuid.UUID | None = None,
    brand_id: uuid.UUID | None = None,
    ctx: TenantContext = Depends(require_metrics),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> CohortsResponse:
    locs, brands, narrowed = _scope(db, ctx, location_id, brand_id)
    cfg = seg.SegmentSettings.of(effective_settings(db))
    as_of = data_as_of(db, ctx.tenant_id, now)
    hide = ctx.role != "hq_owner"
    return CohortsResponse(
        as_of=as_of,
        small_cell_min=cfg.small_cell_min,
        cells_hidden_below_min=hide,
        groups=seg.cohort_groups(db, ctx.tenant_id, locs, brands, narrowed, as_of, cfg, hide),
    )
