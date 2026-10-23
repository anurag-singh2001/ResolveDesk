import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import not_found, require_staff, tenant_db
from app.core.models import Location
from app.core.tenancy import TenantContext

router = APIRouter(tags=["locations"])


class LocationOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


@router.get("/locations")
def list_locations(
    ctx: TenantContext = Depends(require_staff), db: Session = Depends(tenant_db)
) -> list[LocationOut]:
    rows = db.scalars(select(Location).order_by(Location.slug))
    return [
        LocationOut(id=r.id, slug=r.slug, name=r.name) for r in rows if ctx.can_see_location(r.id)
    ]


@router.get("/locations/{location_id}")
def get_location(
    location_id: uuid.UUID,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> LocationOut:
    row = db.get(Location, location_id)  # RLS: another tenant's id is simply not found
    if row is None or not ctx.can_see_location(row.id):
        raise not_found()
    return LocationOut(id=row.id, slug=row.slug, name=row.name)
