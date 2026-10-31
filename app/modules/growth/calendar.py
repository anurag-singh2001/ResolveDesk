"""S11.3a: campaign calendar maths. Pure functions, no database and no writes.

A campaign's calendar window starts when it was sent (`sent_at`) or, until then, at its proposal
expiry (`expires_at`, the latest it could go out), and runs `window_days` (the measurement
window). Warnings are counts of customers, never ids, and never block an approval: the 30-day
frequency cap is enforced where it always was, inside `lapsed_audience` and at send time.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.modules.growth.campaigns import DEFAULT_WINDOW_DAYS, FREQUENCY_CAP_DAYS

# The send states are shown as they are. `pending` (not yet tried) and `skipped` are also real
# member states; none is ever folded into another, least of all into "sent".
SEND_STATES = ("pending", "submitted", "processing", "succeeded", "failed", "unknown", "skipped")
OPEN_STATUSES = frozenset({"pending_approval", "approved"})  # warnings matter before sending
INACTIVE_STATUSES = frozenset({"rejected", "expired"})  # these never contact anyone


def window_of(
    sent_at: datetime | None, expires_at: datetime, window_days: int
) -> tuple[datetime, datetime]:
    start = sent_at or expires_at
    return start, start + timedelta(days=window_days)


def window_days_of(params: dict) -> int:
    value = params.get("window_days")
    return value if type(value) is int and value > 0 else DEFAULT_WINDOW_DAYS


@dataclass
class CalendarItem:
    id: uuid.UUID
    status: str
    start: datetime
    end: datetime
    created_at: datetime
    treated: frozenset[uuid.UUID] = field(default_factory=frozenset)


def warning_counts(items: list[CalendarItem], now: datetime) -> dict[uuid.UUID, tuple[int, int]]:
    """{campaign id: (customers shared with an overlapping campaign, customers inside the
    frequency cap)}. Only open campaigns (pending approval or approved) get non-zero counts, and
    only the other campaigns in `items` (the caller's own scope) are compared, so a count never
    reflects a campaign the caller cannot see. Treatment members only: holdout is never
    contacted."""
    live = [i for i in items if i.status not in INACTIVE_STATUSES]
    cap_from = now - timedelta(days=FREQUENCY_CAP_DAYS)
    out: dict[uuid.UUID, tuple[int, int]] = {}
    for item in items:
        if item.status not in OPEN_STATUSES:
            out[item.id] = (0, 0)
            continue
        overlap: set[uuid.UUID] = set()
        capped: set[uuid.UUID] = set()
        for other in live:
            if other.id == item.id:
                continue
            shared = item.treated & other.treated
            if not shared:
                continue
            if item.start < other.end and other.start < item.end:
                overlap |= shared
            if other.created_at >= cap_from:
                capped |= shared
        out[item.id] = (len(overlap), len(capped))
    return out
