"""S11.4 brand reading rules that need no database: low volume never becomes a trend."""

import uuid
from datetime import UTC, datetime

from app.modules.growth import signals as sig
from app.modules.growth.brand_signals import BrandReading, brand_diagnosis

T = datetime(2026, 1, 1, tzinfo=UTC)


def reading(base_n, recent_n, base_bp, recent_bp, min_orders=sig.MIN_ORDERS):
    z = sig.drop_z_x100(base_bp * base_n // 10000, base_n, recent_bp * recent_n // 10000, recent_n)
    return BrandReading(
        uuid.uuid4(), "B", T, T, T, base_n, recent_n, base_bp, recent_bp, z, min_orders
    )


def test_a_big_drop_on_enough_orders_is_flagged():
    r = reading(200, 200, 5000, 3000)
    assert r.status == "drop" and r.flagged


def test_the_same_drop_on_few_orders_is_low_volume_not_a_drop():
    r = reading(10, 10, 5000, 0)
    assert r.low_volume and r.status == "low_volume" and not r.flagged


def test_either_window_below_the_floor_is_low_volume():
    assert reading(200, 29, 5000, 1000).status == "low_volume"
    assert reading(29, 200, 5000, 1000).status == "low_volume"


def test_the_floor_comes_from_settings_not_the_constant():
    assert reading(20, 20, 5000, 0, min_orders=10).status == "drop"
    assert reading(20, 20, 5000, 0, min_orders=50).status == "low_volume"


def test_a_small_or_noisy_change_is_steady():
    assert reading(200, 200, 5000, 4800).status == "steady"


def test_diagnosis_states_only_the_evidence():
    ev = {
        "baseline": {"orders": 100, "repeat_bp": 5000},
        "recent": {"orders": 90, "repeat_bp": 3000},
        "drop_bp": 2000,
        "tickets_baseline": {"late": 1},
        "tickets_recent": {"late": 4},
        "new_share_baseline_bp": 2000,
        "new_share_recent_bp": 4500,
    }
    d = brand_diagnosis(ev)
    assert any("New customers were 20.0%" in f and "45.0%" in f for f in d.findings)
    assert any("'late' went from 1 to 4" in f for f in d.findings)
    assert d.hypotheses  # guesses stay in their own list


def test_no_ticket_growth_says_the_cause_is_not_visible():
    ev = {
        "baseline": {"orders": 100, "repeat_bp": 5000},
        "recent": {"orders": 90, "repeat_bp": 3000},
        "drop_bp": 2000,
        "tickets_baseline": {},
        "tickets_recent": {},
        "new_share_baseline_bp": None,
        "new_share_recent_bp": None,
    }
    d = brand_diagnosis(ev)
    assert len(d.findings) == 1
    assert any("not visible" in h for h in d.hypotheses)
