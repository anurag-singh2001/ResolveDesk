"""GET /insights/outlets: scope by role, money as integers, and the growth flag on /me.

Runs for every tenant folder and never names one: who sees what comes from the users' roles.
"""

import pytest

from tests.helpers import login

MONEY = ("refunds_confirmed_paise", "vouchers_issued_paise")
COUNTS = ("cases_opened", "refunds_confirmed_count", "vouchers_issued_count", "orders")


def _users(cfg, role):
    return [u for u in cfg.users if u.role == role]


def test_needs_a_token(api):
    assert api.get("/insights/outlets").status_code == 401


def test_only_hq_and_franchisee_owners_may_read(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    for user in cfg.users:
        resp = api.get("/insights/outlets", headers=login(api, cfg.slug, user.email))
        if user.role in ("hq_owner", "franchisee_owner"):
            assert resp.status_code == 200, user.email
        else:
            assert resp.status_code == 403, user.email


def test_hq_sees_every_location_of_its_own_tenant_only(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    for user in _users(cfg, "hq_owner"):
        headers = login(api, cfg.slug, user.email)
        rows = api.get("/insights/outlets", headers=headers).json()
        mine = {loc["id"] for loc in api.get("/locations", headers=headers).json()}
        assert mine  # the tenant has locations
        assert {r["location_id"] for r in rows} == mine  # all of them, and no other tenant's


def test_franchisee_sees_only_their_own_locations(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    for user in _users(cfg, "franchisee_owner"):
        headers = login(api, cfg.slug, user.email)
        own = set(api.get("/me", headers=headers).json()["location_ids"])
        everything = api.get("/insights/outlets", headers=login(api, cfg.slug, _hq(cfg))).json()
        rows = api.get("/insights/outlets", headers=headers).json()
        assert {r["location_id"] for r in rows} == own
        if len(everything) > len(own):  # strictly narrower than HQ's view
            assert len(rows) < len(everything)


def _hq(cfg) -> str:
    return _users(cfg, "hq_owner")[0].email


def test_metrics_are_integers_and_consistent(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    rows = api.get("/insights/outlets", headers=login(api, cfg.slug, _hq(cfg))).json()
    assert rows
    for r in rows:
        assert r["name"]
        for key in (*MONEY, *COUNTS):
            assert type(r[key]) is int and r[key] >= 0, key
        # A count of zero means a total of zero (and the reverse).
        assert (r["refunds_confirmed_count"] == 0) == (r["refunds_confirmed_paise"] == 0)
        assert (r["vouchers_issued_count"] == 0) == (r["vouchers_issued_paise"] == 0)
        assert r["median_decision_minutes"] is None or r["median_decision_minutes"] >= 0
        if r["orders"] == 0:
            assert r["repeat_rate_bp"] is None
        else:
            assert type(r["repeat_rate_bp"]) is int and 0 <= r["repeat_rate_bp"] <= 10000


@pytest.mark.parametrize("flag_role", ["hq_owner", "location_manager", "customer"])
def test_me_reports_the_growth_flag(api, seeded, tenant, flag_role):
    cfg = seeded[tenant.name]
    for user in _users(cfg, flag_role):
        me = api.get("/me", headers=login(api, cfg.slug, user.email)).json()
        assert me["growth_enabled"] is bool(cfg.feature_flags.get("growth"))
