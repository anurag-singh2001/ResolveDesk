"""S11.3b: ROI maths and read-only guarantees. No database."""

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api import routes_growth_roi
from app.modules.growth import roi
from app.modules.growth.roi import Arm


def test_div_round_is_integer_and_symmetric():
    assert roi.div_round(7, 2) == 4
    assert roi.div_round(-7, 2) == -4
    assert roi.div_round(5, 3) == 2
    with pytest.raises(ValueError):
        roi.div_round(1, 0)


def test_incremental_revenue_integer_paise():
    t = Arm(customers=90, ordered=30, orders=40, revenue_paise=900_000)
    h = Arm(customers=10, ordered=2, orders=2, revenue_paise=40_000)
    # 900000/90 = 10000 per treated; 40000/10 = 4000 per held out; (10000-4000)*90 = 540000
    inc = roi.incremental_revenue_paise(t, h)
    assert inc == 540_000 and type(inc) is int
    assert roi.incremental_revenue_paise(Arm(), h) == 0
    assert roi.incremental_revenue_paise(t, Arm()) == 0


def test_cost_is_budget_plus_message_cost_on_succeeded_only():
    assert roi.gross_cost_paise(450_000, 80, 86) == 450_000 + 80 * 86
    assert roi.ratio_bp(-100, 400) == -2500
    assert roi.ratio_bp(100, 0) is None


def test_people_needed_and_detectable_lift():
    assert roi.people_needed_per_arm(2000) > 500
    assert roi.detectable_lift_bp(0, 5) is None
    big = roi.detectable_lift_bp(900, 100)
    small = roi.detectable_lift_bp(90, 10)
    assert big < small


def test_holdout_advice_recommends_more_for_small_audiences_only():
    assert roi.holdout_advice(90, 10, 10)["recommended_holdout_percent"] == 20
    assert roi.holdout_advice(1800, 200, 10)["recommended_holdout_percent"] is None
    assert roi.holdout_advice(80, 20, 20)["recommended_holdout_percent"] is None


def _campaign(sent_days_ago: int | None, now: datetime):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="sent",
        budget_paise=450_000,
        sent_at=None if sent_days_ago is None else now - timedelta(days=sent_days_ago),
        params={"window_days": 14, "treatment_n": 90, "holdout_n": 10, "holdout_percent": 10},
    )


def _report(monkeypatch, arms, sends, *, days=20, verdict=None, settings=None):
    now = datetime(2026, 11, 1, tzinfo=UTC)
    monkeypatch.setattr(roi, "arm_tallies", lambda s, c: (arms, sends))
    return roi.roi_report(None, _campaign(days, now), settings or {}, now, verdict)


SENDS = {**dict.fromkeys(roi.SEND_STATES, 0), "succeeded": 70, "failed": 15, "unknown": 5}


def test_inconclusive_verdict_gates_the_headline(monkeypatch):
    arms = {
        "treatment": Arm(90, 30, 40, 900_000),
        "holdout": Arm(10, 4, 4, 40_000),
    }
    r = _report(monkeypatch, arms, SENDS)  # 10 held out < MIN_ARM_N, so inconclusive
    assert r["gate"] == "inconclusive"
    assert r["headline"] is None and r["incremental_revenue_paise"] is None
    assert r["message"] == "Not enough people to tell"
    assert r["people_needed_per_arm"] > 0
    # Failed and unknown sends stay in the treatment arm and every send state is shown.
    assert r["arms"]["treatment"]["customers"] == 90
    assert r["send_states"]["failed"] == 15 and r["send_states"]["unknown"] == 5
    assert set(r["send_states"]) == set(roi.SEND_STATES)


def test_worked_verdict_gives_headline_with_message_cost_on_succeeded(monkeypatch):
    arms = {"treatment": Arm(200, 100, 120, 2_000_000), "holdout": Arm(100, 20, 22, 300_000)}
    r = _report(monkeypatch, arms, SENDS, verdict="worked")
    assert r["gate"] == "ok"
    assert r["cost"]["message_cost_paise"] == 70 * 86  # defaults; succeeded sends only
    assert r["cost"]["gross_cost_paise"] == 450_000 + 70 * 86
    h = r["headline"]
    assert h["basis"] == "revenue" and h["value_paise"] == 2_000_000 - 300_000 * 2
    assert h["net_paise"] == h["value_paise"] - r["cost"]["gross_cost_paise"]
    assert type(h["ratio_bp"]) is int


def test_margin_basis_is_a_setting_and_labelled(monkeypatch):
    arms = {"treatment": Arm(200, 100, 120, 2_000_000), "holdout": Arm(100, 20, 22, 300_000)}
    s = {"growth_roi_basis": "margin", "growth_gross_margin_bp": 5000}
    r = _report(monkeypatch, arms, SENDS, verdict="worked", settings=s)
    assert r["headline"]["basis"] == "margin"
    assert r["headline"]["value_paise"] == 1_400_000 * 5000 // 10000


def test_open_window_shows_no_headline(monkeypatch):
    arms = {"treatment": Arm(200, 100, 120, 2_000_000), "holdout": Arm(100, 20, 22, 300_000)}
    r = _report(monkeypatch, arms, SENDS, days=3, verdict="worked")
    assert r["gate"] == "window_open" and r["headline"] is None and r["verdict"] is None


def test_report_carries_no_floats(monkeypatch):
    arms = {"treatment": Arm(200, 100, 120, 2_000_000), "holdout": Arm(100, 20, 22, 300_000)}
    r = _report(monkeypatch, arms, SENDS, verdict="worked")

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        else:
            assert not isinstance(x, float)

    walk(r)


def test_roi_read_paths_do_not_write():
    src = inspect.getsource(roi) + inspect.getsource(routes_growth_roi.campaign_roi)
    src += inspect.getsource(routes_growth_roi.channel_mix)
    for word in (".add(", ".commit(", ".delete(", "insert(", "update(", "audit.record"):
        assert word not in src
    assert "audit.record" in inspect.getsource(routes_growth_roi.enter_spend)


def test_spend_input_rejects_floats_negatives_and_whatsapp():
    from pydantic import ValidationError

    ok = {"channel": " Swiggy ", "period_start": "2026-10-01", "period_end": "2026-10-31"}
    assert routes_growth_roi.SpendIn(amount_paise=5000, **ok).channel == "swiggy"
    for bad in (0, -1, 12.5, "100"):
        with pytest.raises(ValidationError):
            routes_growth_roi.SpendIn(amount_paise=bad, **ok)
    with pytest.raises(ValidationError):
        routes_growth_roi.SpendIn(amount_paise=1, **{**ok, "channel": "whatsapp"})
