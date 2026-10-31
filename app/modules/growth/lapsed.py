"""The one meaning of "lapsed" (S11.2).

A customer is lapsed at a scope (one location, or a set of locations and brands) when they have
a non-cancelled order there and the latest one is older than the cut-off. `lapsed_audience`
(win-back campaigns) states it in SQL as "ordered before the cut-off and not since"; the segment
counts apply `is_lapsed` to each customer's latest order. Both take the cut-off from
`lapsed_cut`, so changing the setting `lapsed_days` changes both together.
"""

from datetime import datetime, timedelta

LAPSED_DAYS = 28  # code floor; the setting `lapsed_days` (vertical pack default 28) overrides


MIN_LAPSED_DAYS = 1  # 0 or less would make today's orders "lapsed"


def clamp_lapsed_days(days: int) -> int:
    """The one place the setting is bounded: at least MIN_LAPSED_DAYS."""
    return max(MIN_LAPSED_DAYS, int(days))


def lapsed_cut(as_of: datetime, days: int = LAPSED_DAYS) -> datetime:
    return as_of - timedelta(days=clamp_lapsed_days(days))


def is_lapsed(last_order_at: datetime, as_of: datetime, days: int = LAPSED_DAYS) -> bool:
    return last_order_at < lapsed_cut(as_of, days)
