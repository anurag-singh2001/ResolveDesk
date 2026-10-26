"""E8.1: the repeat-rate signal job and its diagnosis.

Per location, the repeat-customer rate over a recent window is compared with the rate over the
window before it, both computed from the canonical `transactions` table. A drop is flagged only
if it is big enough to matter (>= 5 points, PROJECT.md section 17) AND statistically
distinguishable from noise (one-sided two-proportion z-test), so a quiet outlet with a few
orders does not raise a false alarm.

Rates are stored as integer basis points (hard rule 3's spirit: no floats in stored figures).
The job is idempotent: one signal per (location, metric, recent window end).

The diagnosis is read-only. Code gathers the evidence (ticket categories, new-customer share);
an LLM, if one is configured, only *summarises* that evidence JSON. Without one (and always in
tests) a deterministic template writes the same shape. Either way it makes no writes and
proposes nothing: the proposal is code (campaigns.py), the money decision is a person's.
"""

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.business_time import DEFAULT_TIMEZONE
from app.core.db import tenant_session
from app.core.models import Location, Signal, Transaction
from app.core.settings_resolver import effective_settings

log = logging.getLogger(__name__)

METRIC = "repeat_rate"
RECENT_DAYS = 21
BASELINE_DAYS = 28
LOOKBACK_DAYS = 28  # an order is a "repeat" if the customer ordered here in the 28 days before
MIN_DROP_BP = 500  # 5 percentage points
MIN_ORDERS = 30  # per window: below this a rate is too noisy to flag
Z_MIN_X100 = 164  # one-sided 95%


class Diagnosis(BaseModel):
    findings: list[str] = Field(max_length=10)
    hypotheses: list[str] = Field(max_length=10)


@dataclass(frozen=True)
class Reading:
    """One location's repeat rate in both windows (basis points) and whether it is flagged."""

    location_id: uuid.UUID
    baseline_start: datetime
    recent_start: datetime
    recent_end: datetime
    baseline_n: int
    recent_n: int
    baseline_bp: int
    recent_bp: int
    z_x100: int

    @property
    def drop_bp(self) -> int:
        return self.baseline_bp - self.recent_bp

    @property
    def flagged(self) -> bool:
        return (
            self.baseline_n >= MIN_ORDERS
            and self.recent_n >= MIN_ORDERS
            and self.drop_bp >= MIN_DROP_BP
            and self.z_x100 >= Z_MIN_X100
        )


def repeat_counts(
    session: Session, tenant_id: uuid.UUID, location_id: uuid.UUID, lo: datetime, hi: datetime
) -> tuple[int, int]:
    """(orders, repeat orders) at a location in [lo, hi). A repeat order is one whose customer
    had an earlier, non-cancelled order at the same location within the lookback."""
    row = session.execute(
        text(
            """
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM transactions p
                       WHERE p.tenant_id = t.tenant_id AND p.customer_id = t.customer_id
                         AND p.location_id = t.location_id AND p.status <> 'cancelled'
                         AND p.placed_at < t.placed_at
                         AND p.placed_at >= t.placed_at - make_interval(days => :lookback)
                   )) AS repeats
            FROM transactions t
            WHERE t.tenant_id = :tid AND t.location_id = :loc AND t.status <> 'cancelled'
              AND t.placed_at >= :lo AND t.placed_at < :hi
            """
        ),
        {"tid": tenant_id, "loc": location_id, "lo": lo, "hi": hi, "lookback": LOOKBACK_DAYS},
    ).one()
    return row.n, row.repeats


def drop_z_x100(base_hits: int, base_n: int, recent_hits: int, recent_n: int) -> int:
    """z-score x 100 (an integer) of baseline rate minus recent rate, pooled two-proportion."""
    if base_n == 0 or recent_n == 0:
        return 0
    pooled = (base_hits + recent_hits) / (base_n + recent_n)
    se = math.sqrt(pooled * (1 - pooled) * (1 / base_n + 1 / recent_n))
    if se == 0:
        return 0
    return round((base_hits / base_n - recent_hits / recent_n) / se * 100)


def read_location(
    session: Session, tenant_id: uuid.UUID, location_id: uuid.UUID, as_of: datetime
) -> Reading:
    recent_start = as_of - timedelta(days=RECENT_DAYS)
    baseline_start = recent_start - timedelta(days=BASELINE_DAYS)
    base_n, base_hits = repeat_counts(session, tenant_id, location_id, baseline_start, recent_start)
    recent_n, recent_hits = repeat_counts(session, tenant_id, location_id, recent_start, as_of)
    return Reading(
        location_id=location_id,
        baseline_start=baseline_start,
        recent_start=recent_start,
        recent_end=as_of,
        baseline_n=base_n,
        recent_n=recent_n,
        baseline_bp=round(base_hits * 10000 / base_n) if base_n else 0,
        recent_bp=round(recent_hits * 10000 / recent_n) if recent_n else 0,
        z_x100=drop_z_x100(base_hits, base_n, recent_hits, recent_n),
    )


def data_as_of(session: Session, tenant_id: uuid.UUID, now: datetime) -> datetime:
    """When the job measures up to: the local midnight after the newest order, never later than
    `now`. A nightly job reads the latest complete day of data; with live orders that is today,
    and with a fixed demo history it is the history's last day (not an empty recent window)."""
    latest = session.scalar(
        select(func.max(Transaction.placed_at)).where(Transaction.tenant_id == tenant_id)
    )
    if latest is None:
        return now
    tz = ZoneInfo(effective_settings(session).get("business_timezone") or DEFAULT_TIMEZONE)
    midnight = datetime.combine(latest.astimezone(tz).date() + timedelta(days=1), time(0), tz)
    return min(now, midnight)


def readings(session: Session, tenant_id: uuid.UUID, as_of: datetime) -> list[Reading]:
    """Every location of the tenant (RLS limits the query; the filter is a second layer)."""
    ids = session.scalars(
        select(Location.id).where(Location.tenant_id == tenant_id).order_by(Location.id)
    )
    return [read_location(session, tenant_id, loc, as_of) for loc in ids]


# -- diagnosis (read-only) -------------------------------------------------------------------


def gather_evidence(session: Session, tenant_id: uuid.UUID, r: Reading) -> dict:
    """Read-only drill-down numbers. The same function feeds the template and the LLM."""

    def tickets(lo: datetime, hi: datetime) -> dict[str, int]:
        rows = session.execute(
            text(
                """
                SELECT coalesce(k.category, 'uncategorised') AS category, count(*) AS n
                FROM tickets k JOIN transactions t
                  ON t.tenant_id = k.tenant_id AND t.id = k.transaction_id
                WHERE k.tenant_id = :tid AND t.location_id = :loc
                  AND t.placed_at >= :lo AND t.placed_at < :hi
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"tid": tenant_id, "loc": r.location_id, "lo": lo, "hi": hi},
        )
        return {row.category: row.n for row in rows}

    return {
        "metric": METRIC,
        "baseline": {"orders": r.baseline_n, "repeat_bp": r.baseline_bp},
        "recent": {"orders": r.recent_n, "repeat_bp": r.recent_bp},
        "drop_bp": r.drop_bp,
        "z_x100": r.z_x100,
        "tickets_baseline": tickets(r.baseline_start, r.recent_start),
        "tickets_recent": tickets(r.recent_start, r.recent_end),
    }


def template_diagnosis(evidence: dict) -> Diagnosis:
    """Deterministic summary: states only the numbers above (hard rule 7 for staff-facing text)."""
    base, recent = evidence["baseline"], evidence["recent"]
    findings = [
        f"Repeat-customer rate fell from {base['repeat_bp'] / 100:.1f}% "
        f"({base['orders']} orders) to {recent['repeat_bp'] / 100:.1f}% "
        f"({recent['orders']} orders): a drop of {evidence['drop_bp'] / 100:.1f} points."
    ]
    hypotheses = []
    before, after = evidence["tickets_baseline"], evidence["tickets_recent"]
    grown = sorted(
        (c for c in after if after[c] > before.get(c, 0)),
        key=lambda c: (before.get(c, 0) - after[c], c),
    )
    for category in grown[:3]:
        findings.append(
            f"Tickets in '{category}' went from {before.get(category, 0)} to {after[category]}."
        )
    if grown:
        hypotheses.append(
            f"Service problems ({', '.join(grown[:3])}) may be pushing regulars away; "
            "a win-back offer treats the symptom, so check the cause too."
        )
    else:
        hypotheses.append("No ticket category grew; the cause is not visible in support data.")
    hypotheses.append(
        "A win-back offer to lapsed customers, with a holdout, will show if it helps."
    )
    return Diagnosis(findings=findings, hypotheses=hypotheses)


def llm_client():
    """A chat client only if a provider key is configured and we are not in tests; else None
    (the template is used). Imported lazily: the LLM stack is heavy."""
    from app.config import get_settings

    s = get_settings()
    if s.app_env == "test":
        return None
    keys = {"gemini": s.gemini_api_key, "groq": s.groq_api_key}
    if s.llm_provider != "ollama" and not keys.get(s.llm_provider):
        return None
    from app.llm.providers import LLMClient

    return LLMClient.for_role("main")


def diagnose(evidence: dict, client=None) -> tuple[Diagnosis, str]:
    """(diagnosis, source). The model sees only the evidence JSON (data, not instructions) and
    has no tools; any failure falls back to the template."""
    if client is not None:
        try:
            prompt = [
                (
                    "system",
                    "You summarise a drop in a repeat-customer rate for a business owner. Use "
                    "only the numbers in the JSON the user sends; invent nothing. Reply with "
                    "findings (facts) and hypotheses (clearly labelled guesses).",
                ),
                ("user", str(evidence)),
            ]
            return client.invoke_structured(prompt, Diagnosis), "llm"
        except Exception:
            log.exception("growth diagnosis: LLM failed, using the template")
    return template_diagnosis(evidence), "template"


# -- the job ---------------------------------------------------------------------------------


def _existing(session: Session, r: Reading) -> Signal | None:
    return session.scalar(
        select(Signal).where(
            Signal.location_id == r.location_id,
            Signal.metric == METRIC,
            Signal.recent_end == r.recent_end,
        )
    )


def store_signal(
    session: Session, tenant_id: uuid.UUID, r: Reading, diagnosis: Diagnosis, source: str
) -> Signal:
    """Insert the signal for this window, or return the one already there (re-runs, races)."""
    existing = _existing(session, r)
    if existing is not None:
        return existing
    signal = Signal(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        location_id=r.location_id,
        metric=METRIC,
        baseline_start=r.baseline_start,
        recent_start=r.recent_start,
        recent_end=r.recent_end,
        baseline_bp=r.baseline_bp,
        recent_bp=r.recent_bp,
        baseline_n=r.baseline_n,
        recent_n=r.recent_n,
        drop_bp=r.drop_bp,
        diagnosis=diagnosis.model_dump(),
        diagnosis_source=source,
    )
    try:
        with session.begin_nested():
            session.add(signal)
    except IntegrityError:  # a parallel run stored it first
        return _existing(session, r)
    return signal


def run_signal_job(session: Session, tenant_id: uuid.UUID, as_of: datetime) -> list[Signal]:
    """Compute every location's readings and store a signal for each flagged drop, with the
    template diagnosis (no network, so it is safe inside a request transaction). Re-running is
    a no-op. `session` must be scoped to tenant_id (auth context or a system job)."""
    found = []
    for r in readings(session, tenant_id, as_of):
        if r.flagged:
            diagnosis = template_diagnosis(gather_evidence(session, tenant_id, r))
            found.append(store_signal(session, tenant_id, r, diagnosis, "template"))
    return found


def run_nightly(
    engine: Engine, tenant_id: uuid.UUID, as_of: datetime, client=None
) -> list[uuid.UUID]:
    """The scheduled job, in three phases so no transaction is open during an LLM call (hard
    rule 5): read and flag, summarise, then store. Returns the flagged signals' ids."""
    with tenant_session(tenant_id, engine) as s:
        flagged = [(r, gather_evidence(s, tenant_id, r)) for r in readings(s, tenant_id, as_of)
                   if r.flagged]  # fmt: skip
    diagnosed = [(r, *diagnose(evidence, client)) for r, evidence in flagged]
    with tenant_session(tenant_id, engine) as s:
        return [store_signal(s, tenant_id, r, d, source).id for r, d, source in diagnosed]
