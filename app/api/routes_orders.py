import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_context, not_found, tenant_db
from app.core.models import Fulfilment, LineItem, Transaction
from app.core.tenancy import TenantContext

router = APIRouter(tags=["orders"])


class OrderOut(BaseModel):
    id: uuid.UUID
    external_ref: str
    brand_id: uuid.UUID
    location_id: uuid.UUID
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


def _order_out(t: Transaction) -> dict:
    return {
        "id": t.id,
        "external_ref": t.external_ref,
        "brand_id": t.brand_id,
        "location_id": t.location_id,
        "placed_at": t.placed_at,
        "total_paise": t.total_paise,
        "status": t.status,
    }


@router.get("/orders")
def list_orders(
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> list[OrderOut]:
    rows = db.scalars(
        select(Transaction)
        .where(ctx.visible_orders())
        .order_by(Transaction.placed_at.desc(), Transaction.id)
        .limit(limit)
    )
    return [OrderOut(**_order_out(t)) for t in rows]


@router.get("/orders/{order_id}")
def get_order(
    order_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> OrderDetailOut:
    order = db.scalar(select(Transaction).where(Transaction.id == order_id, ctx.visible_orders()))
    if order is None:
        raise not_found()
    items = db.scalars(
        select(LineItem).where(LineItem.transaction_id == order.id).order_by(LineItem.sku)
    )
    fulfilment = db.scalar(select(Fulfilment).where(Fulfilment.transaction_id == order.id))
    return OrderDetailOut(
        **_order_out(order),
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
