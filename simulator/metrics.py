"""Measure planted problems in generated rows (used by tests; generic over tenants)."""

from collections import defaultdict
from datetime import timedelta

from app.core.tenant_config import ProblemCfg
from simulator.generate import LOCAL_TZ, History, problem_applies

REPEAT_LOOKBACK = timedelta(days=28)


def _orders(history: History, location_ids: dict, problem: ProblemCfg):
    """In-window orders the problem's filters select, with fulfilment and items."""
    fulfilment = {f["transaction_id"]: f for f in history.fulfilments}
    items = defaultdict(list)
    for li in history.line_items:
        items[li["transaction_id"]].append(li)
    slug_of = {v: k for k, v in location_ids.items()}
    for t in history.transactions:
        if t["placed_at"] < history.window_start:
            continue
        local = t["placed_at"].astimezone(LOCAL_TZ)
        if problem_applies(problem, slug_of[t["location_id"]], local):
            yield t, fulfilment[t["id"]], items[t["id"]]


def observed_rate(history: History, location_ids: dict, problem: ProblemCfg) -> tuple[float, int]:
    """(share of the problem's orders that show it, number of orders it applies to)."""
    hits = total = 0
    for _, f, items in _orders(history, location_ids, problem):
        total += 1
        if problem.kind == "late":
            late_by = f["completed_at"] - f["promised_at"]
            hits += late_by >= timedelta(minutes=problem.extra_minutes[0])
        elif problem.kind == "missing_item":
            hits += any(li["quantity_fulfilled"] < li["quantity"] for li in items)
        elif problem.kind == "wrong_item":
            hits += bool(f["attributes"].get("wrong_item"))
    return (hits / total if total else 0.0), total


def repeat_rate(history: History, location_id, start_day: int, end_day: int) -> float:
    """Share of orders at a location (window days [start_day, end_day)) placed by a customer
    who also ordered there in the previous 28 days."""
    last_order: dict = {}
    hits = total = 0
    lo = history.window_start + timedelta(days=start_day)
    hi = history.window_start + timedelta(days=end_day)
    for t in sorted(history.transactions, key=lambda t: t["placed_at"]):
        if t["location_id"] != location_id:
            continue
        prev = last_order.get(t["customer_id"])
        if lo <= t["placed_at"] < hi:
            total += 1
            hits += prev is not None and t["placed_at"] - prev <= REPEAT_LOOKBACK
        last_order[t["customer_id"]] = t["placed_at"]
    return hits / total if total else 0.0
