"""Outlet insights (PROJECT.md section 12): read-only metrics per location, last 30 days.

hq_owner sees every location, franchisee_owner only their own; any other role gets 403 (the
same answer other staff-only routes give). Every query runs in the caller's RLS-scoped session.
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_tenant_context, tenant_db
from app.core.models import Location
from app.core.tenancy import TenantContext
from app.modules.growth.signals import repeat_counts

router = APIRouter(prefix="/insights", tags=["insights"])

WINDOW_DAYS = 30
INSIGHT_ROLES = frozenset({"hq_owner", "franchisee_owner"})
VOUCHER_ACTIONS = ("free_item_voucher", "loyalty_credit")


def require_insights(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if ctx.role not in INSIGHT_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hq_owner or franchisee_owner only")
    return ctx


class OutletInsight(BaseModel):
    location_id: uuid.UUID
    name: str
    cases_opened: int
    refunds_confirmed_count: int
    refunds_confirmed_paise: int
    vouchers_issued_count: int
    vouchers_issued_paise: int
    median_decision_minutes: float | None
    orders: int
    repeat_rate_bp: int | None  # basis points of orders that were repeats; None with no orders


# Cases (and so their proposals) belong to a location through their order. A case or refund
# with no transaction (no order) is not attributed to any location, so it appears in no row.
_CASES = """
    SELECT t.location_id, count(*) AS n FROM cases c
    JOIN transactions t ON t.tenant_id = c.tenant_id AND t.id = c.transaction_id
    WHERE c.tenant_id = :tid AND c.opened_at >= :lo AND c.opened_at < :hi GROUP BY 1
"""
# Approximation: neither refund_operations nor executions has a dedicated "succeeded at" column,
# so a confirmed refund/voucher is bucketed by updated_at. A later touch of a succeeded row (for
# example a verification note) could move it into a newer window.
_REFUNDS = """
    SELECT t.location_id, count(*) AS n, COALESCE(sum(r.amount_paise), 0) AS paise
    FROM refund_operations r
    JOIN transactions t ON t.tenant_id = r.tenant_id AND t.id = r.transaction_id
    WHERE r.tenant_id = :tid AND r.status = 'succeeded'
      AND r.updated_at >= :lo AND r.updated_at < :hi GROUP BY 1
"""
_VOUCHERS = """
    SELECT t.location_id, count(*) AS n, COALESCE(sum(p.amount_paise), 0) AS paise
    FROM executions e
    JOIN action_proposals p ON p.tenant_id = e.tenant_id AND p.id = e.proposal_id
    JOIN cases c ON c.tenant_id = p.tenant_id AND c.id = p.case_id
    JOIN transactions t ON t.tenant_id = c.tenant_id AND t.id = c.transaction_id
    WHERE e.tenant_id = :tid AND e.status = 'succeeded' AND p.action = ANY(:actions)
      AND e.updated_at >= :lo AND e.updated_at < :hi GROUP BY 1
"""
_DECISIONS = """
    SELECT t.location_id,
           percentile_cont(0.5) WITHIN GROUP (
               ORDER BY extract(epoch FROM (a.decided_at - p.created_at)) / 60.0) AS median_min
    FROM approvals a
    JOIN action_proposals p ON p.tenant_id = a.tenant_id AND p.id = a.proposal_id
    JOIN cases c ON c.tenant_id = p.tenant_id AND c.id = p.case_id
    JOIN transactions t ON t.tenant_id = c.tenant_id AND t.id = c.transaction_id
    WHERE a.tenant_id = :tid AND a.decided_at >= :lo AND a.decided_at < :hi GROUP BY 1
"""


@router.get("/outlets")
def outlet_insights(
    ctx: TenantContext = Depends(require_insights),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> list[OutletInsight]:
    lo = now - timedelta(days=WINDOW_DAYS)
    args = {"tid": ctx.tenant_id, "lo": lo, "hi": now}

    def by_location(sql: str, **extra):
        return {r.location_id: r for r in db.execute(text(sql), {**args, **extra})}

    cases = by_location(_CASES)
    refunds = by_location(_REFUNDS)
    vouchers = by_location(_VOUCHERS, actions=list(VOUCHER_ACTIONS))
    decisions = by_location(_DECISIONS)

    out: list[OutletInsight] = []
    for loc in db.scalars(select(Location).order_by(Location.slug)):
        if not ctx.can_see_location(loc.id):
            continue
        orders, repeats = repeat_counts(db, ctx.tenant_id, loc.id, lo, now)
        r, v, d = refunds.get(loc.id), vouchers.get(loc.id), decisions.get(loc.id)
        out.append(
            OutletInsight(
                location_id=loc.id,
                name=loc.name,
                cases_opened=cases[loc.id].n if loc.id in cases else 0,
                refunds_confirmed_count=r.n if r else 0,
                refunds_confirmed_paise=int(r.paise) if r else 0,
                vouchers_issued_count=v.n if v else 0,
                vouchers_issued_paise=int(v.paise) if v else 0,
                median_decision_minutes=round(float(d.median_min), 1) if d else None,
                orders=orders,
                repeat_rate_bp=round(repeats * 10000 / orders) if orders else None,
            )
        )
    return out
