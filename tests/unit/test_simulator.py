"""Simulator at full scale, in memory: determinism, volumes, planted problems, money."""

import math
import uuid
from collections import Counter
from functools import cache

import pytest

from app.core.tenant_config import load_tenant, tenant_dirs
from app.core.verticals import load_pack
from simulator.generate import Refs, generate
from simulator.metrics import observed_rate, repeat_rate

TOLERANCE = 0.01  # spec: planted rates within +-1 percentage point


def _refs(cfg) -> Refs:
    tid = uuid.uuid5(uuid.NAMESPACE_URL, cfg.slug)
    return Refs(
        tenant_id=tid,
        brand_ids={b.slug: uuid.uuid5(tid, b.slug) for b in cfg.brands},
        location_ids={loc.slug: uuid.uuid5(tid, loc.slug) for loc in cfg.locations},
        user_ids={u.email: uuid.uuid5(tid, u.email) for u in cfg.users},
    )


@cache
def _run(folder_name: str, seed: int = 42):
    cfg = load_tenant(next(p for p in tenant_dirs() if p.name == folder_name))
    refs = _refs(cfg)
    return cfg, refs, generate(cfg, load_pack(cfg.vertical_pack), refs, seed=seed)


@pytest.fixture
def run(tenant):
    cfg, refs, history = _run(tenant.name)
    if cfg.simulation is None:
        pytest.skip("tenant has no simulation config")
    return cfg, refs, history


def test_same_seed_same_data_other_seed_different(run, tenant):
    cfg, refs, history = run
    again = generate(cfg, load_pack(cfg.vertical_pack), refs, seed=42)
    assert again.checksum() == history.checksum()
    assert _run(tenant.name, seed=7)[2].checksum() != history.checksum()


def test_volumes_match_config(run):
    cfg, _, h = run
    sim = cfg.simulation
    in_window = [t for t in h.transactions if t["placed_at"] >= h.window_start]
    assert len(in_window) == sim.orders
    assert len(h.transactions) - len(in_window) == sim.messy.orders_outside_window
    assert len(h.customers) == sim.customers
    assert len(h.tickets) == sim.past_tickets


def test_planted_rates_within_tolerance(run):
    cfg, refs, h = run
    rated = [p for p in cfg.simulation.problems if p.kind != "repeat_drop"]
    assert rated or cfg.simulation.problems == []
    for p in rated:
        observed, n = observed_rate(h, refs.location_ids, p)
        # +-1 point on large populations; narrow slices (one outlet, two hours, weekdays) are a
        # few hundred orders, where +-1 point is below sampling noise, so allow 3 standard errors.
        tolerance = max(TOLERANCE, 3 * math.sqrt(p.rate * (1 - p.rate) / n))
        assert abs(observed - p.rate) <= tolerance, (p, observed, n)


def test_repeat_drop_is_detectable(run):
    """The growth signal flags drops > 5 points vs the location's own baseline."""
    cfg, refs, h = run
    drops = [p for p in cfg.simulation.problems if p.kind == "repeat_drop"]
    if not drops:
        pytest.skip("no repeat_drop planted for this tenant")
    for p in drops:
        location_id = refs.location_ids[p.location]
        before = repeat_rate(h, location_id, 7, p.from_day)
        after = repeat_rate(h, location_id, p.from_day, cfg.simulation.days)
        assert before - after > 0.05, (before, after)
        others = [v for k, v in refs.location_ids.items() if k != p.location]
        for other in others:  # and only where it was planted
            assert repeat_rate(h, other, p.from_day, cfg.simulation.days) > after + 0.05


def test_messy_data_present(run):
    cfg, _, h = run
    messy = cfg.simulation.messy
    phones = Counter(c["phone"] for c in h.customers)
    dup_share = sum(1 for c in h.customers if phones[c["phone"]] > 1) / len(h.customers)
    assert dup_share >= messy.duplicate_phone_rate  # each dupe makes >= 2 rows share a phone
    opted_out = [c for c in h.consents if c["purpose"] == "marketing" and not c["granted"]]
    assert abs(len(opted_out) / len(h.customers) - messy.opted_out_rate) <= 0.02


def test_money_is_integer_paise_and_adds_up(run):
    _, _, h = run
    for _, rows in h.tables():
        for row in rows:
            for key, value in row.items():
                if key.endswith("_paise"):
                    assert type(value) is int and value >= 0, (key, value)
    line_totals = Counter()
    for li in h.line_items:
        assert li["total_paise"] == li["unit_price_paise"] * li["quantity"]
        line_totals[li["transaction_id"]] += li["total_paise"]
    paid = {p["transaction_id"]: p["amount_paise"] for p in h.payments}
    for t in h.transactions:
        assert t["total_paise"] == line_totals[t["id"]] == paid[t["id"]]


def test_demo_customers_are_linked_and_have_orders(run):
    cfg, refs, h = run
    by_user = {c["user_id"]: c["id"] for c in h.customers if c["user_id"]}
    ordering = {t["customer_id"] for t in h.transactions}
    for user in (u for u in cfg.users if u.role == "customer"):
        customer_id = by_user[refs.user_ids[user.email]]
        assert customer_id in ordering
