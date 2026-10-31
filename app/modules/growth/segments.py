"""S11.2: customer segments and first-order cohorts. Read only, aggregates only.

Everything is computed at request time from `transactions`, `customers` and `consents`; no
table. A customer id, phone or consent flag is used inside this module to count and to
de-duplicate, and none of them is ever part of what it returns (the models below hold counts and
paise only). Segments overlap on purpose (a loyal customer is also active), so shares of the base
do not add up to 100.

Segment rules (every threshold is a setting; see the vertical packs):
  new            first order in scope within `segment_new_days`
  active         latest order within `lapsed_days` (the complement of lapsed)
  loyal          active, 2+ orders, and in the top `segment_loyal_top_percent` of the group on
                 BOTH order count and spend (nearest rank, so ties can make it a little larger)
  at_risk        active, 2+ orders, and quiet for more than `segment_at_risk_gap_multiple` times
                 their own average gap between orders
  lapsed         latest order older than `lapsed_days` (app.modules.growth.lapsed)
  lapsed_regular lapsed, and would have counted as loyal by history
  one_and_done   exactly one order, older than the "new" window
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.business_time import DEFAULT_TIMEZONE
from app.modules.growth.lapsed import lapsed_cut

SEGMENTS = ("new", "active", "loyal", "at_risk", "lapsed", "lapsed_regular", "one_and_done")
COHORT_MONTHS = 6
RETURN_MONTHS = (1, 2, 3)


class SegmentCell(BaseModel):
    segment: str
    suppressed: bool  # true: fewer customers than the small-cell minimum, numbers withheld
    in_segment: int | None
    share_bp: int | None  # of the group's customers, basis points
    orders: int | None
    total_spend_paise: int | None
    aov_paise: int | None
    # Latest WhatsApp marketing consent granted, a phone present, one customer per phone.
    # Always a separate number from in_segment, which counts everyone regardless of consent.
    contactable_whatsapp: int | None
    own_channel: int | None  # ordered at least once outside the aggregator sources
    aggregator_only: int | None  # every order came through a delivery app
    aggregator_only_not_contactable: int | None  # of those, with no consent row at all


class SegmentGroup(BaseModel):
    id: uuid.UUID | None  # brand id, or None for the whole scope
    name: str
    customers: int
    segments: list[SegmentCell]


class CohortCell(BaseModel):
    month: int  # months after the first order
    measurable: bool  # false: that calendar month is not over yet
    returned: int | None
    return_bp: int | None


class CohortRow(BaseModel):
    cohort_month: date
    suppressed: bool
    size: int | None
    cells: list[CohortCell]


class CohortGroup(BaseModel):
    id: uuid.UUID | None
    name: str
    cohorts: list[CohortRow]


@dataclass(frozen=True)
class SegmentSettings:
    lapsed_days: int
    new_days: int
    at_risk_multiple: int
    loyal_top_percent: int
    small_cell_min: int
    aggregator_sources: tuple[str, ...]

    @classmethod
    def of(cls, settings: dict) -> "SegmentSettings":
        return cls(
            lapsed_days=int(settings["lapsed_days"]),
            new_days=int(settings["segment_new_days"]),
            at_risk_multiple=int(settings["segment_at_risk_gap_multiple"]),
            loyal_top_percent=int(settings["segment_loyal_top_percent"]),
            small_cell_min=int(settings["small_cell_min"]),
            aggregator_sources=tuple(settings.get("aggregator_order_sources") or ()),
        )


@dataclass(frozen=True)
class _Cust:
    """One customer's history inside one group. Never leaves this module."""

    orders: int
    first_at: datetime
    last_at: datetime
    spend: int
    agg_orders: int
    phone: str
    wa_granted: bool
    has_consent: bool


_ROWS = """
    SELECT {g} AS grp, t.customer_id AS cid, COALESCE(c.phone, '') AS phone,
           count(*) AS n, min(t.placed_at) AS first_at, max(t.placed_at) AS last_at,
           COALESCE(sum(t.total_paise), 0) AS spend,
           count(*) FILTER (WHERE t.source = ANY(:agg)) AS agg_n,
           COALESCE((SELECT k.granted FROM consents k WHERE k.tenant_id = t.tenant_id
               AND k.customer_id = t.customer_id AND k.channel = 'whatsapp'
               AND k.purpose = 'marketing'), false) AS wa,
           EXISTS (SELECT 1 FROM consents k WHERE k.tenant_id = t.tenant_id
               AND k.customer_id = t.customer_id) AS any_consent
    FROM transactions t JOIN customers c ON c.tenant_id = t.tenant_id AND c.id = t.customer_id
    WHERE t.tenant_id = :tid AND t.status <> 'cancelled'
      AND t.location_id = ANY(CAST(:locs AS uuid[])){brand}
    GROUP BY 1, 2, 3, t.tenant_id
"""
_MONTHS = """
    SELECT {g} AS grp, t.customer_id AS cid,
           date_trunc('month', t.placed_at AT TIME ZONE :tz)::date AS m
    FROM transactions t
    WHERE t.tenant_id = :tid AND t.status <> 'cancelled'
      AND t.location_id = ANY(CAST(:locs AS uuid[])){brand}
    GROUP BY 1, 2, 3
"""


def _run(db, template, by_brand, tenant_id, locs, brands, narrowed, extra):
    brand_sql = " AND t.brand_id = ANY(CAST(:brands AS uuid[]))" if narrowed else ""
    sql = template.format(g="t.brand_id" if by_brand else "NULL::uuid", brand=brand_sql)
    params = {"tid": tenant_id, "locs": [str(i) for i in locs], **extra}
    if narrowed:
        params["brands"] = [str(b) for b, _ in brands]
    return db.execute(text(sql), params)


def _threshold(values: list[int], top_percent: int) -> int:
    """The value at the nearest-rank cut, so about `top_percent` of the values are >= it."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, len(ordered) * (100 - top_percent) // 100)]


def classify(custs: list[_Cust], as_of: datetime, cfg: SegmentSettings) -> dict[str, list[_Cust]]:
    new_cut = as_of - timedelta(days=cfg.new_days)
    cut = lapsed_cut(as_of, cfg.lapsed_days)
    out: dict[str, list[_Cust]] = {s: [] for s in SEGMENTS}
    if not custs:
        return out
    n_cut = _threshold([c.orders for c in custs], cfg.loyal_top_percent)
    spend_cut = _threshold([c.spend for c in custs], cfg.loyal_top_percent)
    for c in custs:
        lapsed = c.last_at < cut  # the rule lapsed_audience uses (lapsed.is_lapsed)
        loyal_by_history = c.orders >= 2 and c.orders >= n_cut and c.spend >= spend_cut
        if c.first_at >= new_cut:
            out["new"].append(c)
        if lapsed:
            out["lapsed"].append(c)
            if loyal_by_history:
                out["lapsed_regular"].append(c)
        else:
            out["active"].append(c)
            if loyal_by_history:
                out["loyal"].append(c)
            # quiet for more than multiple x average gap, compared without division
            if c.orders >= 2 and c.last_at > c.first_at:
                quiet = as_of - c.last_at
                if quiet * (c.orders - 1) > (c.last_at - c.first_at) * cfg.at_risk_multiple:
                    out["at_risk"].append(c)
        if c.orders == 1 and c.first_at < new_cut:
            out["one_and_done"].append(c)
    return out


def _cell(name: str, members: list[_Cust], base: int, hide_small: bool, cfg) -> SegmentCell:
    if hide_small and len(members) < cfg.small_cell_min:
        return SegmentCell(
            segment=name, suppressed=True, in_segment=None, share_bp=None, orders=None,
            total_spend_paise=None, aov_paise=None, contactable_whatsapp=None,
            own_channel=None, aggregator_only=None, aggregator_only_not_contactable=None,
        )  # fmt: skip
    orders = sum(c.orders for c in members)
    spend = sum(c.spend for c in members)
    phones = {c.phone for c in members if c.wa_granted and c.phone}  # one per phone
    agg_only = [c for c in members if c.agg_orders == c.orders]
    return SegmentCell(
        segment=name,
        suppressed=False,
        in_segment=len(members),
        share_bp=round(len(members) * 10000 / base) if base else 0,
        orders=orders,
        total_spend_paise=spend,
        aov_paise=spend // orders if orders else None,
        contactable_whatsapp=len(phones),
        own_channel=len(members) - len(agg_only),
        aggregator_only=len(agg_only),
        aggregator_only_not_contactable=sum(1 for c in agg_only if not c.has_consent),
    )


def segment_groups(
    db: Session,
    tenant_id: uuid.UUID,
    location_ids: list[uuid.UUID],
    brands: list[tuple[uuid.UUID, str]],
    narrowed: bool,
    as_of: datetime,
    cfg: SegmentSettings,
    hide_small: bool,
) -> list[SegmentGroup]:
    """The whole scope first, then one group per brand in scope."""
    extra = {"agg": list(cfg.aggregator_sources)}
    by_group: dict[tuple[bool, uuid.UUID | None], list[_Cust]] = {}
    for by_brand in (False, True):
        for r in _run(db, _ROWS, by_brand, tenant_id, location_ids, brands, narrowed, extra):
            by_group.setdefault((by_brand, r.grp), []).append(
                _Cust(
                    r.n, r.first_at, r.last_at, int(r.spend), r.agg_n, r.phone, r.wa, r.any_consent
                )  # fmt: skip
            )
    todo = [(False, None, "All brands")] + [(True, b, n) for b, n in brands]
    out = []
    for by_brand, gid, name in todo:
        custs = by_group.get((by_brand, gid), [])
        by_segment = classify(custs, as_of, cfg)
        cells = [_cell(s, by_segment[s], len(custs), hide_small, cfg) for s in SEGMENTS]
        out.append(SegmentGroup(id=gid, name=name, customers=len(custs), segments=cells))
    return out


def _unmeasured(k: int) -> CohortCell:
    return CohortCell(month=k, measurable=False, returned=None, return_bp=None)


def add_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def cohort_groups(
    db: Session,
    tenant_id: uuid.UUID,
    location_ids: list[uuid.UUID],
    brands: list[tuple[uuid.UUID, str]],
    narrowed: bool,
    as_of: datetime,
    cfg: SegmentSettings,
    hide_small: bool,
) -> list[CohortGroup]:
    """First-order-month cohorts for the last COHORT_MONTHS months (the month of `as_of`
    included), with the share who ordered again in month 1, 2 and 3 after it. A month that is
    not over yet is not measurable. A customer's first order is their first within the scope.
    A hidden cohort (fewer than the minimum, non-HQ roles) shows no size and no rates."""
    this_month = as_of.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date().replace(day=1)
    months = [add_months(this_month, -i) for i in range(COHORT_MONTHS - 1, -1, -1)]
    seen: dict[tuple[bool, uuid.UUID | None], dict[uuid.UUID, set[date]]] = {}
    extra = {"tz": DEFAULT_TIMEZONE}
    for by_brand in (False, True):
        for r in _run(db, _MONTHS, by_brand, tenant_id, location_ids, brands, narrowed, extra):
            seen.setdefault((by_brand, r.grp), {}).setdefault(r.cid, set()).add(r.m)
    out = []
    for by_brand, gid, name in [(False, None, "All brands")] + [(True, b, n) for b, n in brands]:
        customers = seen.get((by_brand, gid), {}).values()
        rows = []
        for m in months:
            cohort = [s for s in customers if min(s) == m]
            if hide_small and len(cohort) < cfg.small_cell_min:
                rows.append(CohortRow(cohort_month=m, suppressed=True, size=None, cells=[]))
                continue
            cells = []
            for k in RETURN_MONTHS:
                target = add_months(m, k)
                if target >= this_month:  # that month is not over yet
                    cells.append(_unmeasured(k))
                    continue
                back = sum(1 for s in cohort if target in s)
                bp = round(back * 10000 / len(cohort)) if cohort else None
                cells.append(CohortCell(month=k, measurable=True, returned=back, return_bp=bp))
            rows.append(CohortRow(cohort_month=m, suppressed=False, size=len(cohort), cells=cells))
        out.append(CohortGroup(id=gid, name=name, cohorts=rows))
    return out
