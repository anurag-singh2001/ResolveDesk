"""S11.3a calendar maths: windows and the read-only warning counts."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.growth.calendar import (
    SEND_STATES,
    CalendarItem,
    warning_counts,
    window_days_of,
    window_of,
)

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def cust(n):
    return uuid.UUID(int=n)


def item(n, status, start_days, window=14, created_days_ago=0, members=()):
    start = NOW + timedelta(days=start_days)
    return CalendarItem(
        uuid.UUID(int=1000 + n),
        status,
        start,
        start + timedelta(days=window),
        NOW - timedelta(days=created_days_ago),
        frozenset(cust(m) for m in members),
    )


def test_window_starts_at_sent_at_or_else_expiry():
    sent, exp = NOW, NOW + timedelta(days=2)
    assert window_of(sent, exp, 14) == (sent, sent + timedelta(days=14))
    assert window_of(None, exp, 7) == (exp, exp + timedelta(days=7))


def test_bad_window_days_fall_back_to_default():
    assert window_days_of({"window_days": 10}) == 10
    assert window_days_of({"window_days": True}) == window_days_of({})
    assert window_days_of({"window_days": 0}) == window_days_of({})


def test_the_send_states_stay_distinct():
    for state in ("submitted", "processing", "succeeded", "failed", "unknown"):
        assert state in SEND_STATES
    assert "sent" not in SEND_STATES
    assert len(set(SEND_STATES)) == len(SEND_STATES)


def test_overlapping_windows_with_shared_customers_are_counted():
    a = item(1, "pending_approval", 0, members=[1, 2, 3])
    b = item(2, "approved", 5, members=[3, 4, 2])
    out = warning_counts([a, b], NOW)
    assert out[a.id][0] == 2 and out[b.id][0] == 2


def test_no_overlap_in_time_or_no_shared_customer_gives_no_overlap_warning():
    a = item(1, "pending_approval", 0, members=[1, 2])
    later = item(2, "approved", 14, members=[1, 2])  # starts exactly when a ends
    apart = item(3, "approved", 3, members=[8, 9])
    out = warning_counts([a, later, apart], NOW)
    assert out[a.id][0] == 0 and out[later.id][0] == 0 and out[apart.id][0] == 0


def test_frequency_cap_counts_shared_customers_in_a_recent_campaign():
    recent = item(1, "approved", 100, created_days_ago=5, members=[1, 2])
    old = item(2, "sent", 100, created_days_ago=40, members=[3])
    mine = item(3, "pending_approval", 200, members=[1, 3, 4])
    out = warning_counts([recent, old, mine], NOW)
    assert out[mine.id] == (0, 1)  # customer 1 only: the other campaign of 3 is 40 days old


def test_rejected_and_expired_campaigns_neither_warn_nor_cause_warnings():
    dead = item(1, "rejected", 0, members=[1, 2])
    gone = item(2, "expired", 0, members=[1, 2])
    mine = item(3, "pending_approval", 0, members=[1, 2])
    out = warning_counts([dead, gone, mine], NOW)
    assert out[mine.id] == (0, 0) and out[dead.id] == (0, 0)


def test_warnings_for_sent_campaigns_are_zero_and_plain_counts():
    sent = item(1, "sent", 0, members=[1])
    other = item(2, "pending_approval", 0, members=[1])
    out = warning_counts([sent, other], NOW)
    assert out[sent.id] == (0, 0)
    assert out[other.id] == (1, 1)
    assert all(isinstance(n, int) for pair in out.values() for n in pair)
