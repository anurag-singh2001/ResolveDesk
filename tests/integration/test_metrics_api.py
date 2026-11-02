"""GET /insights/metrics: role scoping, 404 scoping, integer paise and explicit empty days.

Runs for every tenant folder and never names one: scope comes from each user's role.
"""

import uuid
from dataclasses import replace
from datetime import date, timedelta

import pytest
from fastapi import Depends

from app.api.deps import _request_session, get_tenant_context
from tests.helpers import login

URL = "/insights/metrics"
PAISE = ("refunds_paise", "vouchers_paise", "remedy_spend_paise", "revenue_paise")
INTS = (
    "cases_opened",
    "refunds_count",
    "vouchers_count",
    "decisions",
    "orders",
    "repeat_orders",
    "ai_decided",
    "ai_overridden",
    *PAISE,
)
OPT_BP = ("sla_met_bp", "repeat_rate_bp", "ai_accuracy_bp")


def _users(cfg, role):
    return [u for u in cfg.users if u.role == role]


def _hdr(api, cfg, role):
    users = _users(cfg, role)
    if not users:
        pytest.skip(f"this tenant has no {role}")
    return login(api, cfg.slug, users[0].email)


def _by_location(api, headers, **params):
    resp = api.get(URL, params={"group_by": "location", **params}, headers=headers)
    assert resp.status_code == 200, resp.text
    return {g["id"]: g for g in resp.json()["groups"]}


def _total(group, key):
    return sum(p[key] for p in group["points"])


def test_needs_a_token(api):
    assert api.get(URL).status_code == 401


def test_customers_are_refused(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    for user in _users(cfg, "customer")[:1]:
        assert api.get(URL, headers=login(api, cfg.slug, user.email)).status_code == 403


def test_hq_sees_all_locations_and_scoped_roles_only_their_own(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    hq = _hdr(api, cfg, "hq_owner")
    everything = _by_location(api, hq)
    assert set(everything) == {loc["id"] for loc in api.get("/locations", headers=hq).json()}
    for role in ("franchisee_owner", "location_manager"):
        for user in _users(cfg, role):
            headers = login(api, cfg.slug, user.email)
            own = set(api.get("/me", headers=headers).json()["location_ids"])
            mine = _by_location(api, headers)
            assert set(mine) == own, (role, user.email)
            for lid, group in mine.items():  # same numbers HQ sees for those outlets
                assert group["points"] == everything[lid]["points"]
            total = api.get(URL, headers=headers).json()["groups"][0]
            for key in ("orders", "revenue_paise", "cases_opened"):
                assert _total(total, key) == sum(_total(g, key) for g in mine.values())


def test_location_filter_narrows_and_out_of_scope_is_404(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    everything = _by_location(api, _hdr(api, cfg, "hq_owner"))
    for user in _users(cfg, "location_manager") + _users(cfg, "franchisee_owner"):
        headers = login(api, cfg.slug, user.email)
        own = set(api.get("/me", headers=headers).json()["location_ids"])
        for lid in own:
            ok = api.get(URL, params={"location_id": lid}, headers=headers)
            assert ok.status_code == 200
            assert _total(ok.json()["groups"][0], "orders") == _total(everything[lid], "orders")
        for lid in set(everything) - own:
            resp = api.get(URL, params={"location_id": lid}, headers=headers)
            assert resp.status_code == 404, (user.email, lid)


def test_other_tenants_ids_are_404(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    others = [c for name, c in seeded_history.items() if name != tenant.name]
    if not others:
        pytest.skip("only one tenant")
    foreign_hq = _hdr(api, others[0], "hq_owner")
    foreign_loc = api.get("/locations", headers=foreign_hq).json()[0]["id"]
    foreign_brand = api.get(URL, params={"group_by": "brand"}, headers=foreign_hq).json()["groups"][
        0
    ]["id"]
    hq = _hdr(api, cfg, "hq_owner")
    assert api.get(URL, params={"location_id": foreign_loc}, headers=hq).status_code == 404
    assert api.get(URL, params={"brand_id": foreign_brand}, headers=hq).status_code == 404


def test_brand_filter_and_brand_grouping(api, seeded_history, tenant):
    hq = _hdr(api, seeded_history[tenant.name], "hq_owner")
    whole = api.get(URL, headers=hq).json()["groups"][0]
    brands = api.get(URL, params={"group_by": "brand"}, headers=hq).json()["groups"]
    assert brands
    for key in ("orders", "revenue_paise"):
        assert sum(_total(g, key) for g in brands) == _total(whole, key)
    for g in brands:
        one = api.get(URL, params={"brand_id": g["id"]}, headers=hq).json()["groups"][0]
        assert _total(one, "orders") == _total(g, "orders")


def test_brand_limited_caller_sees_only_their_brand(api, seeded_history, tenant):
    # No seeded user is limited to a brand, so limit the real caller's context for this request.
    hq = _hdr(api, seeded_history[tenant.name], "hq_owner")
    brands = api.get(URL, params={"group_by": "brand"}, headers=hq).json()["groups"]
    if len(brands) < 2:
        pytest.skip("this tenant has one brand")
    mine, other = brands[0], brands[1]
    as_hq = api.get(URL, params={"brand_id": mine["id"]}, headers=hq).json()["groups"][0]

    def limited(session=Depends(_request_session, scope="function")):
        return replace(session.info["ctx"], brand_ids=frozenset({uuid.UUID(mine["id"])}))

    api.app.dependency_overrides[get_tenant_context] = limited
    try:
        total = api.get(URL, headers=hq).json()["groups"][0]
        grouped = api.get(URL, params={"group_by": "brand"}, headers=hq).json()["groups"]
        refused = api.get(URL, params={"brand_id": other["id"]}, headers=hq)
    finally:
        del api.app.dependency_overrides[get_tenant_context]
    assert total["points"] == as_hq["points"]  # repeat orders included: no other brand's orders
    assert [g["id"] for g in grouped] == [mine["id"]]
    assert refused.status_code == 404


def test_paise_are_ints_and_derived_values_are_consistent(api, seeded_history, tenant):
    hq = _hdr(api, seeded_history[tenant.name], "hq_owner")
    body = api.get(URL, params={"days": 60}, headers=hq).json()
    assert body["decision_sla_minutes"] > 0
    points = body["groups"][0]["points"]
    assert sum(p["orders"] for p in points) > 0  # the seeded history is visible
    for p in points:
        for key in INTS:
            assert type(p[key]) is int and p[key] >= 0, key
        assert p["remedy_spend_paise"] == p["refunds_paise"] + p["vouchers_paise"]
        assert sum(p["cases_by_category"].values()) == p["cases_opened"]
        assert p["ai_overridden"] <= p["ai_decided"]
        for key in OPT_BP:
            assert p[key] is None or (type(p[key]) is int and 0 <= p[key] <= 10000), key
        if p["orders"]:
            assert type(p["aov_paise"]) is int
            assert p["aov_paise"] == p["revenue_paise"] // p["orders"]
        else:
            assert p["aov_paise"] is None and p["repeat_rate_bp"] is None


def test_empty_days_are_explicit(api, seeded_history, tenant):
    hq = _hdr(api, seeded_history[tenant.name], "hq_owner")
    body = api.get(URL, params={"days": 90}, headers=hq).json()
    points = body["groups"][0]["points"]
    days = [date.fromisoformat(p["bucket_start"]) for p in points]
    assert len(days) == 90
    assert all(b - a == timedelta(days=1) for a, b in zip(days, days[1:], strict=False))
    assert days[-1] == date.fromisoformat(body["end"])
    quiet = [p for p in points if not p["orders"] and not p["cases_opened"]]
    assert quiet, "a 90 day window is expected to hold at least one empty day"
    for p in quiet:
        assert p["cases_by_category"] == {} and p["remedy_spend_paise"] == 0
        assert p["median_decision_minutes"] is None and p["aov_paise"] is None


def test_weekly_buckets_are_whole_mondays(api, seeded_history, tenant):
    hq = _hdr(api, seeded_history[tenant.name], "hq_owner")
    body = api.get(URL, params={"granularity": "week", "days": 30}, headers=hq).json()
    starts = [date.fromisoformat(p["bucket_start"]) for p in body["groups"][0]["points"]]
    assert len(starts) >= 4
    assert all(d.weekday() == 0 for d in starts)
    assert all(b - a == timedelta(days=7) for a, b in zip(starts, starts[1:], strict=False))


def test_bad_parameters_are_422(api, seeded_history, tenant):
    hq = _hdr(api, seeded_history[tenant.name], "hq_owner")
    assert api.get(URL, params={"granularity": "month"}, headers=hq).status_code == 422
    assert api.get(URL, params={"days": 0}, headers=hq).status_code == 422
    assert api.get(URL, params={"days": 5000}, headers=hq).status_code == 422
