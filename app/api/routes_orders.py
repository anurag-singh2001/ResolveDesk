import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_context, not_found, tenant_db
from app.core.models import Brand, Fulfilment, LineItem, Location, Transaction
from app.core.tenancy import TenantContext

router = APIRouter(tags=["orders"])


class OrderOut(BaseModel):
    id: uuid.UUID
    external_ref: str
    brand_id: uuid.UUID
    location_id: uuid.UUID
    brand_name: str
    location_name: str
    placed_at: datetime
    total_paise: int
    status: str


class LineItemOut(BaseModel):
    sku: str
    name: str
    quantity: int
    quantity_fulfilled: int
    total_paise: int


class OrderDetailOut(OrderOut):
    items: list[LineItemOut]
    # What the customer was promised and when it actually arrived/was ready.
    promised_at: datetime | None = None
    completed_at: datetime | None = None


def _order_out(t: Transaction, brand_name: str, location_name: str) -> dict:
    return {
        "id": t.id,
        "external_ref": t.external_ref,
        "brand_id": t.brand_id,
        "location_id": t.location_id,
        "brand_name": brand_name,
        "location_name": location_name,
        "placed_at": t.placed_at,
        "total_paise": t.total_paise,
        "status": t.status,
    }


def _with_names():
    """Orders with their brand and location names (same tenant: composite FKs + RLS)."""
    return (
        select(Transaction, Brand.name, Location.name)
        .join(Brand, Brand.id == Transaction.brand_id)
        .join(Location, Location.id == Transaction.location_id)
    )


@router.get("/orders")
def list_orders(
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> list[OrderOut]:
    rows = db.execute(
        _with_names()
        .where(ctx.visible_orders())
        .order_by(Transaction.placed_at.desc(), Transaction.id)
        .limit(limit)
    )
    return [OrderOut(**_order_out(*r)) for r in rows]


@router.get("/orders/{order_id}")
def get_order(
    order_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> OrderDetailOut:
    row = db.execute(_with_names().where(Transaction.id == order_id, ctx.visible_orders())).first()
    if row is None:
        raise not_found()
    order = row[0]
    items = db.scalars(
        select(LineItem).where(LineItem.transaction_id == order.id).order_by(LineItem.sku)
    )
    fulfilment = db.scalar(select(Fulfilment).where(Fulfilment.transaction_id == order.id))
    return OrderDetailOut(
        **_order_out(*row),
        promised_at=fulfilment.promised_at if fulfilment else None,
        completed_at=fulfilment.completed_at if fulfilment else None,
        items=[
            LineItemOut(
                sku=i.sku,
                name=i.name,
                quantity=i.quantity,
                quantity_fulfilled=i.quantity_fulfilled,
                total_paise=i.total_paise,
            )
            for i in items
        ],
    )
