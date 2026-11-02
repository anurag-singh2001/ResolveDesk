"""Segment rules without a database: classification, thresholds, the shared lapsed rule and
the vertical-pack defaults. Tenant-neutral by construction."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.verticals import load_pack
from app.modules.growth import lapsed
from app.modules.growth.segments import (
    SEGMENTS,
    SegmentSettings,
    _cell,
    _Cust,
    _threshold,
    add_months,
    classify,
)

NOW = datetime(2026, 6, 30, tzinfo=UTC)
CFG = SegmentSettings(
    lapsed_days=28,
    new_days=30,
    at_risk_multiple=2,
    loyal_top_percent=20,
    small_cell_min=10,
    aggregator_sources=("agg",),
)


def cust(orders, first_days_ago, last_days_ago, spend=1000, agg=0, phone="p", wa=True, any_c=True):
    return _Cust(
        orders=orders,
        first_at=NOW - timedelta(days=first_days_ago),
        last_at=NOW - timedelta(days=last_days_ago),
        spend=spend,
        agg_orders=agg,
        phone=phone,
        wa_granted=wa,
        has_consent=any_c,
    )


def names(by_segment, key):
    return len(by_segment[key])


def test_segments_cover_the_documented_set():
    assert SEGMENTS == (
        "new", "active", "loyal", "at_risk", "lapsed", "lapsed_regular", "one_and_done"
    )  # fmt: skip


def test_rules_on_a_small_base():
    base = [
        cust(1, 5, 5),  # new, active
        cust(1, 200, 200),  # one and done, lapsed
        cust(2, 200, 10),  # active; gap 190 days, quiet 10 -> not at risk
        cust(3, 120, 100),  # lapsed; avg gap 10 days
        cust(5, 150, 60, spend=9000),  # lapsed + loyal by history
        cust(6, 150, 1, spend=9000),  # loyal and active
        cust(4, 100, 50, spend=100),  # lapsed (50 > 28)
        cust(3, 40, 27, spend=100),  # active; gap 6.5 days, quiet 27 > 13 -> at risk
    ]
    out = classify(base, NOW, CFG)
    assert names(out, "new") == 1
    assert names(out, "one_and_done") == 1
    assert names(out, "lapsed") == 4
    assert names(out, "active") == len(base) - 4
    assert names(out, "lapsed_regular") >= 1 and all(
        c.last_at < NOW - timedelta(days=28) for c in out["lapsed_regular"]
    )
    assert out["loyal"] and all(c.last_at >= NOW - timedelta(days=28) for c in out["loyal"])
    assert any(c.last_at == NOW - timedelta(days=27) for c in out["at_risk"])
    assert not any(c.orders == 1 for c in out["at_risk"] + out["loyal"] + out["lapsed_regular"])


def test_new_customer_is_not_one_and_done_and_empty_base_is_empty():
    out = classify([cust(1, 3, 3)], NOW, CFG)
    assert names(out, "new") == 1 and names(out, "one_and_done") == 0
    assert all(v == [] for v in classify([], NOW, CFG).values())


def test_lapsed_boundary_matches_the_shared_rule():
    cut = lapsed.lapsed_cut(NOW, 28)
    assert cut == NOW - timedelta(days=28)
    on = cust(2, 100, 28)  # exactly at the cut-off is NOT lapsed: "not since" means >= cut
    assert not lapsed.is_lapsed(on.last_at, NOW, 28)
    assert classify([on], NOW, CFG)["lapsed"] == []
    past = cust(2, 100, 29)
    assert (
        lapsed.is_lapsed(past.last_at, NOW, 28) and len(classify([past], NOW, CFG)["lapsed"]) == 1
    )


def test_threshold_is_nearest_rank_and_integer():
    assert _threshold(list(range(100)), 20) == 80
    assert _threshold([5], 20) == 5
    assert _threshold([1, 2, 3, 4, 5], 20) == 5


def test_cell_counts_everyone_but_contacts_one_per_phone_with_latest_consent():
    members = [
        cust(1, 5, 5, phone="1", wa=True),
        cust(1, 5, 5, phone="1", wa=True),  # duplicate phone: one contact
        cust(1, 5, 5, phone="2", wa=False, any_c=True),  # withdrawn / not granted
        cust(1, 5, 5, phone="3", wa=False, any_c=False),  # no consent row
        cust(1, 5, 5, phone="", wa=True),  # consent but no phone
        cust(1, 5, 5, phone="4", wa=False, any_c=False, agg=1),  # aggregator only, no consent
    ]
    c = _cell("active", members, len(members), hide_small=False, cfg=CFG)
    assert c.in_segment == 6 and c.contactable_whatsapp == 1
    assert c.aggregator_only == 1 and c.aggregator_only_not_contactable == 1
    assert c.own_channel == 5
    assert c.aov_paise == 1000 and c.total_spend_paise == 6000
    assert isinstance(c.total_spend_paise, int) and isinstance(c.share_bp, int)


def test_small_cells_are_withheld_only_when_asked():
    members = [cust(1, 5, 5) for _ in range(9)]
    hidden = _cell("new", members, 9, hide_small=True, cfg=CFG)
    assert hidden.suppressed and hidden.in_segment is None and hidden.contactable_whatsapp is None
    shown = _cell("new", members + [cust(1, 5, 5)], 10, hide_small=True, cfg=CFG)
    assert not shown.suppressed and shown.in_segment == 10
    assert not _cell("new", members, 9, hide_small=False, cfg=CFG).suppressed


def test_add_months():
    assert add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)


@pytest.mark.parametrize("pack", ["cloud_kitchen", "coffee_chain"])
def test_every_vertical_pack_has_segment_defaults(pack):
    specs = load_pack(pack).settings
    cfg = SegmentSettings.of({k: s.default for k, s in specs.items()})
    assert (cfg.lapsed_days, cfg.new_days, cfg.at_risk_multiple) == (28, 30, 2)
    assert (cfg.loyal_top_percent, cfg.small_cell_min) == (20, 10)
    assert cfg.lapsed_days == lapsed.LAPSED_DAYS


# -- complementary suppression and the lapsed bound ----------------------------------------------

import random  # noqa: E402

from app.modules.growth.segments import CUSTOMERS, hide_plan  # noqa: E402

SUMS = ((CUSTOMERS, "active", "lapsed"),)
NAMES = [CUSTOMERS, *SEGMENTS]


def solvable(sizes, hidden, groups, names=NAMES, sums=SUMS):
    """Any relation left with exactly one hidden term lets a reader compute that term."""
    relations = [[(g, t) for t in trio] for g in range(groups) for trio in sums]
    if groups > 1:
        relations += [[(g, n) for g in range(groups)] for n in names]
    return [r for r in relations if sum(t in hidden for t in r) == 1]


def test_a_lone_small_lapsed_cell_also_hides_active():
    sizes = {(0, CUSTOMERS): 100, (0, "active"): 95, (0, "lapsed"): 5}
    sizes.update({(0, s): 50 for s in SEGMENTS if s not in ("active", "lapsed")})
    hidden = hide_plan(sizes, 1, NAMES, 10, SUMS)
    assert {(0, "lapsed"), (0, "active")} <= hidden and (0, CUSTOMERS) not in hidden


def test_a_small_brand_cell_hides_a_sibling_so_it_cannot_be_subtracted():
    # group 0 = all brands, 1 and 2 = brands; brand 2's "new" is small
    sizes = {(g, n): 50 for g in range(3) for n in NAMES}
    sizes.update({(0, CUSTOMERS): 200, (1, CUSTOMERS): 120, (2, CUSTOMERS): 80})
    sizes[(2, "new")] = 4
    hidden = hide_plan(sizes, 3, NAMES, 10, SUMS)
    assert (2, "new") in hidden and len({g for g, n in hidden if n == "new"}) >= 2
    assert not solvable(sizes, hidden, 3)


def test_no_hidden_value_can_be_derived_whatever_the_sizes():
    rng = random.Random(42)
    for _ in range(300):
        groups = rng.randint(1, 4)
        sizes = {(g, n): rng.randint(0, 40) for g in range(groups) for n in NAMES}
        hidden = hide_plan(sizes, groups, NAMES, 10, SUMS)
        assert all(k in hidden for k, v in sizes.items() if v < 10)  # small ones always hidden
        if groups > 1:  # a lone group has nothing to difference against across groups
            assert not solvable(sizes, hidden, groups)
        else:
            assert not [r for r in solvable(sizes, hidden, 1)]


def test_a_visible_cell_shows_no_share_when_the_group_total_is_hidden():
    from app.modules.growth.segments import _visible_cell

    assert _visible_cell("active", [], None).share_bp is None
    assert _visible_cell("active", [], 0).share_bp == 0


def test_nothing_extra_is_hidden_when_nothing_is_small():
    sizes = {(g, n): 30 for g in range(3) for n in NAMES}
    assert hide_plan(sizes, 3, NAMES, 10, SUMS) == set()


def test_lapsed_days_is_bounded_in_one_place():
    assert lapsed.clamp_lapsed_days(0) == 1 and lapsed.clamp_lapsed_days(-5) == 1
    assert lapsed.clamp_lapsed_days(28) == 28
    assert lapsed.lapsed_cut(NOW, 0) == NOW - timedelta(days=1)
    assert lapsed.lapsed_cut(NOW, -9) == NOW - timedelta(days=1)
    assert not lapsed.is_lapsed(NOW, NOW, 0)  # an order from now is never lapsed
    cfg = SegmentSettings.of(
        {"lapsed_days": 0, "segment_new_days": 30, "segment_at_risk_gap_multiple": 2,
         "segment_loyal_top_percent": 20, "small_cell_min": 10}
    )  # fmt: skip
    assert cfg.lapsed_days == 1
