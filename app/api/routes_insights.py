"""Outlet insights (PROJECT.md section 12): read-only metrics per location, last 30 days.

hq_owner sees every location, franchisee_owner only their own; any other role gets 403 (the
same answer other staff-only routes give). Every query runs in the caller's RLS-scoped session.
"""

import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_tenant_context, not_found, tenant_db
from app.core.business_time import DEFAULT_TIMEZONE
from app.core.models import Brand, Location
from app.core.tenancy import TenantContext
from app.modules.growth.signals import LOOKBACK_DAYS, repeat_counts

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


# --- Metrics time series (S10.2) ----------------------------------------------------------
# Same attribution as the outlet insights above: a case, refund, voucher or decision belongs to
# the location and brand of the order it is about. Buckets are calendar days (or ISO weeks) in
# the business timezone, because an order at 01:00 IST belongs to that local day.

METRIC_ROLES = frozenset({"hq_owner", "franchisee_owner", "location_manager"})
MAX_DAYS = 366
DECISION_SLA_MINUTES = 240  # a proposal decided within 4 hours meets the SLA
UNCATEGORISED = "uncategorised"


def require_metrics(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if ctx.role not in METRIC_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "staff with a metrics role only")
    return ctx


class MetricPoint(BaseModel):
    bucket_start: date
    cases_opened: int
    cases_by_category: dict[str, int]
    refunds_count: int
    refunds_paise: int
    vouchers_count: int
    vouchers_paise: int
    remedy_spend_paise: int
    decisions: int
    median_decision_minutes: float | None
    sla_met_bp: int | None  # basis points of decisions made within DECISION_SLA_MINUTES
    orders: int
    repeat_orders: int
    repeat_rate_bp: int | None
    revenue_paise: int
    aov_paise: int | None
    ai_decided: int
    ai_overridden: int
    ai_accuracy_bp: int | None  # basis points of AI proposals staff did not override


class MetricGroup(BaseModel):
    id: uuid.UUID | None
    name: str
    points: list[MetricPoint]


class MetricsResponse(BaseModel):
    granularity: str
    timezone: str
    start: date
    end: date
    decision_sla_minutes: int
    groups: list[MetricGroup]


_TX = "JOIN transactions t ON t.tenant_id = {a}.tenant_id AND t.id = {a}.transaction_id"
_PCASE = (
    "JOIN action_proposals p ON p.tenant_id = {a}.tenant_id AND p.id = {a}.proposal_id "
    "JOIN cases c ON c.tenant_id = p.tenant_id AND c.id = p.case_id "
    "JOIN transactions t ON t.tenant_id = c.tenant_id AND t.id = c.transaction_id"
)
_SCOPE = "t.tenant_id = :tid AND t.location_id = ANY(CAST(:locs AS uuid[])){brand}"

_M_CASES = (
    "SELECT {g} AS grp, {b:c.opened_at} AS bk, COALESCE(c.category, :unc) AS cat, "
    "count(*) AS n FROM cases c "
    + _TX.format(a="c")
    + " WHERE "
    + _SCOPE
    + " AND c.opened_at >= :lo AND c.opened_at < :hi GROUP BY 1, 2, 3"
)
_M_REFUNDS = (
    "SELECT {g} AS grp, {b:r.updated_at} AS bk, count(*) AS n, "
    "COALESCE(sum(r.amount_paise), 0) AS paise FROM refund_operations r "
    + _TX.format(a="r")
    + " WHERE "
    + _SCOPE
    + " AND r.status = 'succeeded' AND r.updated_at >= :lo AND r.updated_at < :hi GROUP BY 1, 2"
)
_M_VOUCHERS = (
    "SELECT {g} AS grp, {b:e.updated_at} AS bk, count(*) AS n, "
    "COALESCE(sum(p.amount_paise), 0) AS paise FROM executions e "
    + _PCASE.format(a="e")
    + " WHERE "
    + _SCOPE
    + " AND e.status = 'succeeded' AND p.action = ANY(:actions)"
    " AND e.updated_at >= :lo AND e.updated_at < :hi GROUP BY 1, 2"
)
_M_DECISIONS = (
    "SELECT {g} AS grp, {b:a.decided_at} AS bk, count(*) AS n, "
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY "
    "extract(epoch FROM (a.decided_at - p.created_at)) / 60.0) AS med, "
    "count(*) FILTER (WHERE a.decided_at - p.created_at <= make_interval(mins => :sla)) AS met "
    "FROM approvals a "
    + _PCASE.format(a="a")
    + " WHERE "
    + _SCOPE
    # Auto-approvals are instant, so counting them would flatter the SLA and the median.
    + " AND a.mode = 'human' AND a.decided_at >= :lo AND a.decided_at < :hi GROUP BY 1, 2"
)
_M_ORDERS = (
    "SELECT {g} AS grp, {b:t.placed_at} AS bk, count(*) AS n, "
    "COALESCE(sum(t.total_paise), 0) AS paise, "
    "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM transactions q "
    "WHERE q.tenant_id = t.tenant_id AND q.customer_id = t.customer_id "
    "AND q.location_id = t.location_id{repeat_brand} "
    "AND q.status <> 'cancelled' AND q.placed_at < t.placed_at "
    "AND q.placed_at >= t.placed_at - make_interval(days => :lookback))) AS repeats "
    "FROM transactions t WHERE "
    + _SCOPE
    + " AND t.status <> 'cancelled' AND t.placed_at >= :lo AND t.placed_at < :hi GROUP BY 1, 2"
)
# AI accuracy: proposals the engine made (proposed_by IS NULL) that a person then decided or
# switched. Overridden = a person rejected it, or an approver switched it to another remedy.
_M_AI = (
    "SELECT {g} AS grp, {b:p.created_at} AS bk, count(*) AS n, "
    "count(*) FILTER (WHERE s.old_proposal_id IS NOT NULL OR "
    "(a.decision = 'rejected' AND a.mode = 'human')) AS over "
    "FROM action_proposals p "
    "JOIN cases c ON c.tenant_id = p.tenant_id AND c.id = p.case_id "
    "JOIN transactions t ON t.tenant_id = c.tenant_id AND t.id = c.transaction_id "
    "LEFT JOIN approvals a ON a.tenant_id = p.tenant_id AND a.proposal_id = p.id "
    "LEFT JOIN proposal_supersessions s ON s.tenant_id = p.tenant_id "
    "AND s.old_proposal_id = p.id WHERE "
    + _SCOPE
    + " AND p.proposed_by IS NULL AND (a.id IS NOT NULL OR s.old_proposal_id IS NOT NULL) "
    "AND p.created_at >= :lo AND p.created_at < :hi GROUP BY 1, 2"
)


def _bp(part: int, whole: int) -> int | None:
    return round(part * 10000 / whole) if whole else None


@router.get("/metrics")
def metrics(
    granularity: Literal["day", "week"] = "day",
    days: int = Query(30, ge=1, le=MAX_DAYS),
    location_id: uuid.UUID | None = None,
    brand_id: uuid.UUID | None = None,
    group_by: Literal["none", "location", "brand"] = "none",
    ctx: TenantContext = Depends(require_metrics),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> MetricsResponse:
    # Scope comes from the caller's membership; a client-supplied id can only narrow it, and an
    # id outside the scope (or in another tenant, which RLS hides) is a 404.
    visible = [
        loc
        for loc in db.scalars(select(Location).order_by(Location.slug))
        if ctx.can_see_location(loc.id)
    ]
    if location_id is not None:
        visible = [loc for loc in visible if loc.id == location_id]
        if not visible:
            raise not_found()
    brands = [
        b
        for b in db.scalars(select(Brand).order_by(Brand.slug))
        if not ctx.brand_ids or b.id in ctx.brand_ids
    ]
    if brand_id is not None:
        brands = [b for b in brands if b.id == brand_id]
        if not brands:
            raise not_found()
    narrowed_brands = brand_id is not None or bool(ctx.brand_ids)

    tz = ZoneInfo(DEFAULT_TIMEZONE)
    end = now.astimezone(tz).date()
    start = end - timedelta(days=days - 1)
    if granularity == "week":
        start -= timedelta(days=start.weekday())  # whole weeks, so the first bucket is complete
    lo = datetime.combine(start, time.min, tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)

    gexpr = {"none": "NULL::uuid", "location": "t.location_id", "brand": "t.brand_id"}[group_by]
    params = {
        "tid": ctx.tenant_id,
        "locs": [str(loc.id) for loc in visible],
        "lo": lo,
        "hi": hi,
        "tz": DEFAULT_TIMEZONE,
        "unc": UNCATEGORISED,
        "actions": list(VOUCHER_ACTIONS),
        "sla": DECISION_SLA_MINUTES,
        "lookback": LOOKBACK_DAYS,
    }
    if narrowed_brands:
        params["brands"] = [str(b.id) for b in brands]
    brand_sql = " AND t.brand_id = ANY(CAST(:brands AS uuid[]))" if narrowed_brands else ""
    # Repeat orders look back only through brands in scope, so a brand-limited caller's figure
    # never depends on orders in a brand they cannot see.
    repeat_brand_sql = brand_sql.replace("t.brand_id", "q.brand_id")

    def run(sql: str):
        sql = re.sub(
            r"\{b:([\w.]+)\}",
            lambda m: f"date_trunc('{granularity}', {m.group(1)} AT TIME ZONE :tz)::date",
            sql,
        )
        sql = sql.replace("{g}", gexpr).replace("{brand}", brand_sql)
        sql = sql.replace("{repeat_brand}", repeat_brand_sql)
        return db.execute(text(sql), params)

    # Every bucket in the window exists as a row, zero or not, so a chart shows a gap as zero.
    step = timedelta(days=7 if granularity == "week" else 1)
    buckets = []
    d = start
    while d <= end:
        buckets.append(d)
        d += step

    if group_by == "location":
        group_rows = [(loc.id, loc.name) for loc in visible]
    elif group_by == "brand":
        group_rows = [(b.id, b.name) for b in brands]
    else:
        group_rows = [(None, "all")]
    acc = {
        (g, bk): {
            "cat": {},
            "r": (0, 0),
            "v": (0, 0),
            "d": (0, None, 0),
            "o": (0, 0, 0),
            "a": (0, 0),
        }
        for g, _ in group_rows
        for bk in buckets
    }

    def slot(row):
        return acc.get((row.grp, row.bk))

    for r in run(_M_CASES):
        if s := slot(r):
            s["cat"][r.cat] = r.n
    for r in run(_M_REFUNDS):
        if s := slot(r):
            s["r"] = (r.n, int(r.paise))
    for r in run(_M_VOUCHERS):
        if s := slot(r):
            s["v"] = (r.n, int(r.paise))
    for r in run(_M_DECISIONS):
        if s := slot(r):
            s["d"] = (r.n, round(float(r.med), 1), r.met)
    for r in run(_M_ORDERS):
        if s := slot(r):
            s["o"] = (r.n, int(r.paise), r.repeats)
    for r in run(_M_AI):
        if s := slot(r):
            s["a"] = (r.n, r.over)

    groups = []
    for g, name in group_rows:
        points = []
        for bk in buckets:
            s = acc[(g, bk)]
            orders, revenue, repeats = s["o"]
            ai_n, ai_over = s["a"]
            points.append(
                MetricPoint(
                    bucket_start=bk,
                    cases_opened=sum(s["cat"].values()),
                    cases_by_category=dict(sorted(s["cat"].items())),
                    refunds_count=s["r"][0],
                    refunds_paise=s["r"][1],
                    vouchers_count=s["v"][0],
                    vouchers_paise=s["v"][1],
                    remedy_spend_paise=s["r"][1] + s["v"][1],
                    decisions=s["d"][0],
                    median_decision_minutes=s["d"][1],
                    sla_met_bp=_bp(s["d"][2], s["d"][0]),
                    orders=orders,
                    repeat_orders=repeats,
                    repeat_rate_bp=_bp(repeats, orders),
                    revenue_paise=revenue,
                    aov_paise=revenue // orders if orders else None,
                    ai_decided=ai_n,
                    ai_overridden=ai_over,
                    ai_accuracy_bp=_bp(ai_n - ai_over, ai_n),
                )
            )
        groups.append(MetricGroup(id=g, name=name, points=points))
    return MetricsResponse(
        granularity=granularity,
        timezone=DEFAULT_TIMEZONE,
        start=start,
        end=end,
        decision_sla_minutes=DECISION_SLA_MINUTES,
        groups=groups,
    )
