"""S11.4: repeat-rate signals per brand, computed on read (no table, no stored rows).

Same windows, thresholds and z-test as the location job in signals.py, which supplies them.
Only the counting differs: a repeat order is one whose customer had an earlier non-cancelled
order *of the same brand* (any location) in the lookback. So a customer who orders from two
brands is counted as repeat within each brand separately.

Computing on read keeps this idempotent by construction (same data and as_of give the same
answer) and needs no migration. Nothing is stored, sent or proposed. Output is aggregates only.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.models import Brand
from app.core.settings_resolver import effective_settings
from app.modules.growth import signals as sig

MIN_ORDERS_KEY = "growth_min_orders"  # per-window floor; pack default, falls back to the job's


@dataclass(frozen=True)
class BrandReading:
    brand_id: uuid.UUID
    name: str
    baseline_start: datetime
    recent_start: datetime
    recent_end: datetime
    baseline_n: int
    recent_n: int
    baseline_bp: int
    recent_bp: int
    z_x100: int
    min_orders: int

    @property
    def low_volume(self) -> bool:
        return self.baseline_n < self.min_orders or self.recent_n < self.min_orders

    @property
    def drop_bp(self) -> int:
        return self.baseline_bp - self.recent_bp

    @property
    def flagged(self) -> bool:
        return (
            not self.low_volume
            and self.drop_bp >= sig.MIN_DROP_BP
            and self.z_x100 >= sig.Z_MIN_X100
        )

    @property
    def status(self) -> str:
        return "low_volume" if self.low_volume else "drop" if self.flagged else "steady"


def brand_repeat_counts(
    session: Session, tenant_id: uuid.UUID, brand_id: uuid.UUID, lo: datetime, hi: datetime
) -> tuple[int, int]:
    """(orders, repeat orders) of a brand in [lo, hi), across all its locations."""
    row = session.execute(
        text(
            """
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM transactions p
                       WHERE p.tenant_id = t.tenant_id AND p.customer_id = t.customer_id
                         AND p.brand_id = t.brand_id AND p.status <> 'cancelled'
                         AND p.placed_at < t.placed_at
                         AND p.placed_at >= t.placed_at - make_interval(days => :lookback)
                   )) AS repeats
            FROM transactions t
            WHERE t.tenant_id = :tid AND t.brand_id = :brand AND t.status <> 'cancelled'
              AND t.placed_at >= :lo AND t.placed_at < :hi
            """
        ),
        {
            "tid": tenant_id,
            "brand": brand_id,
            "lo": lo,
            "hi": hi,
            "lookback": sig.LOOKBACK_DAYS,
        },
    ).one()
    return row.n, row.repeats


def read_brand(
    session: Session, tenant_id: uuid.UUID, brand: Brand, as_of: datetime, min_orders: int
) -> BrandReading:
    recent_start = as_of - timedelta(days=sig.RECENT_DAYS)
    baseline_start = recent_start - timedelta(days=sig.BASELINE_DAYS)
    base_n, base_hits = brand_repeat_counts(
        session, tenant_id, brand.id, baseline_start, recent_start
    )
    recent_n, recent_hits = brand_repeat_counts(session, tenant_id, brand.id, recent_start, as_of)
    return BrandReading(
        brand_id=brand.id,
        name=brand.name,
        baseline_start=baseline_start,
        recent_start=recent_start,
        recent_end=as_of,
        baseline_n=base_n,
        recent_n=recent_n,
        baseline_bp=round(base_hits * 10000 / base_n) if base_n else 0,
        recent_bp=round(recent_hits * 10000 / recent_n) if recent_n else 0,
        z_x100=sig.drop_z_x100(base_hits, base_n, recent_hits, recent_n),
        min_orders=min_orders,
    )


def new_customer_share_bp(
    session: Session, tenant_id: uuid.UUID, brand_id: uuid.UUID, lo: datetime, hi: datetime
) -> int | None:
    """Share (basis points) of the brand's orders in the window placed by a customer with no
    earlier order of that brand. None with no orders."""
    row = session.execute(
        text(
            """
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE NOT EXISTS (
                       SELECT 1 FROM transactions p
                       WHERE p.tenant_id = t.tenant_id AND p.customer_id = t.customer_id
                         AND p.brand_id = t.brand_id AND p.status <> 'cancelled'
                         AND p.placed_at < t.placed_at
                   )) AS firsts
            FROM transactions t
            WHERE t.tenant_id = :tid AND t.brand_id = :brand AND t.status <> 'cancelled'
              AND t.placed_at >= :lo AND t.placed_at < :hi
            """
        ),
        {"tid": tenant_id, "brand": brand_id, "lo": lo, "hi": hi},
    ).one()
    return round(row.firsts * 10000 / row.n) if row.n else None


def brand_evidence(session: Session, tenant_id: uuid.UUID, r: BrandReading) -> dict:
    """Same shape as signals.gather_evidence, but ticket categories are by the order's brand."""

    def tickets(lo: datetime, hi: datetime) -> dict[str, int]:
        rows = session.execute(
            text(
                """
                SELECT coalesce(k.category, 'uncategorised') AS category, count(*) AS n
                FROM tickets k JOIN transactions t
                  ON t.tenant_id = k.tenant_id AND t.id = k.transaction_id
                WHERE k.tenant_id = :tid AND t.brand_id = :brand
                  AND t.placed_at >= :lo AND t.placed_at < :hi
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"tid": tenant_id, "brand": r.brand_id, "lo": lo, "hi": hi},
        )
        return {row.category: row.n for row in rows}

    return {
        "metric": sig.METRIC,
        "baseline": {"orders": r.baseline_n, "repeat_bp": r.baseline_bp},
        "recent": {"orders": r.recent_n, "repeat_bp": r.recent_bp},
        "drop_bp": r.drop_bp,
        "z_x100": r.z_x100,
        "tickets_baseline": tickets(r.baseline_start, r.recent_start),
        "tickets_recent": tickets(r.recent_start, r.recent_end),
        "new_share_baseline_bp": new_customer_share_bp(
            session, tenant_id, r.brand_id, r.baseline_start, r.recent_start
        ),
        "new_share_recent_bp": new_customer_share_bp(
            session, tenant_id, r.brand_id, r.recent_start, r.recent_end
        ),
    }


def brand_diagnosis(evidence: dict) -> sig.Diagnosis:
    """The location template (findings vs hypotheses), plus the new-customer share as a finding.
    Only data-backed statements; no cause is invented."""
    d = sig.template_diagnosis(evidence)
    before, after = evidence["new_share_baseline_bp"], evidence["new_share_recent_bp"]
    if before is not None and after is not None:
        d.findings.append(
            f"New customers were {sig.format_pct(before)}% of orders before and "
            f"{sig.format_pct(after)}% in the recent window."
        )
    return d


def brand_readings(
    session: Session, tenant_id: uuid.UUID, brand_ids: frozenset[uuid.UUID], as_of: datetime
) -> list[BrandReading]:
    """Readings for the tenant's brands, limited to `brand_ids` when it is not empty."""
    floor = effective_settings(session).get(MIN_ORDERS_KEY, sig.MIN_ORDERS)
    brands = session.scalars(select(Brand).where(Brand.tenant_id == tenant_id).order_by(Brand.slug))
    return [
        read_brand(session, tenant_id, b, as_of, floor)
        for b in brands
        if not brand_ids or b.id in brand_ids
    ]
