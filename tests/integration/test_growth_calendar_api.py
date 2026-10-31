"""GET /growth/calendar: scope, read-only, counts only, distinct send states.

Runs for every tenant folder and never names one: who sees what comes from each user's role.
"""

import json
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.api.deps import get_clock
from app.core.db import tenant_session
from app.core.models import Campaign, CampaignMember, Customer
from tests.helpers import login
from tests.integration.test_growth import ctx_of, gt, propose_for  # noqa: F401

URL = "/growth/calendar"
SEND_KEYS = {"pending", "submitted", "processing", "succeeded", "failed", "unknown", "skipped"}


@pytest.fixture
def cal(api, app_engine, gt):  # noqa: F811
    cfg, tid, as_of = gt
    if not cfg.feature_flags.get("growth"):
        pytest.skip("growth is off for this tenant")
    staff = [u for u in cfg.users if u.role != "customer"]
    headers = {u.email: login(api, cfg.slug, u.email) for u in staff}
    api.app.dependency_overrides[get_clock] = lambda: as_of  # after login: tokens use real time
    hq = next(u.email for u in staff if u.role == "hq_owner")
    try:
        signals = api.post("/growth/signals/refresh", headers=headers[hq]).json()
        hq_ctx = ctx_of(app_engine, tid, hq)
        made = 0
        for s in signals:
            try:
                propose_for(app_engine, tid, uuid.UUID(s["id"]), hq_ctx, as_of)
                made += 1
            except Exception:  # a location with too small an audience cannot run a campaign
                continue
        if not made:
            pytest.skip("no location has an eligible audience")
        yield api, cfg, tid, headers, staff, hq
    finally:
        api.app.dependency_overrides.pop(get_clock, None)


def test_hq_lists_every_campaign_with_dates_and_counts(cal, app_engine):
    api, cfg, tid, headers, staff, hq = cal
    resp = api.get(URL, headers=headers[hq])
    assert resp.status_code == 200, resp.text
    rows = resp.json()["campaigns"]
    with tenant_session(tid, app_engine) as s:
        stored = {c.id: c for c in s.scalars(select(Campaign))}
    assert {uuid.UUID(r["id"]) for r in rows} == set(stored)
    for r in rows:
        c = stored[uuid.UUID(r["id"])]
        assert r["status"] == c.status == "pending_approval"
        assert type(r["budget_paise"]) is int and r["budget_paise"] == c.budget_paise
        assert r["audience_n"] == r["treatment_n"] + r["holdout_n"]
        # Not sent yet: the calendar starts at the proposal expiry.
        start = datetime.fromisoformat(r["start"])
        assert start == c.expires_at
        assert datetime.fromisoformat(r["window_end"]) == start + timedelta(days=r["window_days"])
        assert set(r["send_counts"]) == SEND_KEYS
        assert r["send_counts"]["pending"] == r["treatment_n"]
        assert r["overlap_customers"] >= 0 and r["frequency_cap_customers"] >= 0


def test_the_response_has_no_customer_ids_names_or_phones(cal, app_engine):
    api, cfg, tid, headers, staff, hq = cal
    text = json.dumps(api.get(URL, headers=headers[hq]).json())
    with tenant_session(tid, app_engine) as s:
        for cid, name, phone in s.execute(select(Customer.id, Customer.name, Customer.phone)):
            assert str(cid) not in text
            assert not name or name not in text
            assert not phone or phone not in text


def test_scoped_staff_see_only_campaigns_at_their_locations(cal):
    api, cfg, tid, headers, staff, hq = cal
    everything = {r["id"] for r in api.get(URL, headers=headers[hq]).json()["campaigns"]}
    for u in staff:
        resp = api.get(URL, headers=headers[u.email])
        assert resp.status_code == 200
        rows = resp.json()["campaigns"]
        assert {r["id"] for r in rows} <= everything
        if u.role == "hq_owner":
            assert {r["id"] for r in rows} == everything
            continue
        visible = {x["id"] for x in api.get("/locations", headers=headers[u.email]).json()}
        assert {r["location_id"] for r in rows} <= visible


def test_a_location_out_of_scope_is_404(cal):
    api, cfg, tid, headers, staff, hq = cal
    all_locs = {x["id"] for x in api.get("/locations", headers=headers[hq]).json()}
    for u in (u for u in staff if u.role != "hq_owner"):
        mine = {x["id"] for x in api.get("/locations", headers=headers[u.email]).json()}
        for loc in all_locs - mine:
            resp = api.get(URL, params={"location_id": loc}, headers=headers[u.email])
            assert resp.status_code == 404
    unknown = {"location_id": str(uuid.uuid4())}
    assert api.get(URL, params=unknown, headers=headers[hq]).status_code == 404
    unknown = {"brand_id": str(uuid.uuid4())}
    assert api.get(URL, params=unknown, headers=headers[hq]).status_code == 404


def test_the_calendar_is_read_only(cal, app_engine):
    api, cfg, tid, headers, staff, hq = cal

    def snapshot():
        with tenant_session(tid, app_engine) as s:
            return (
                s.scalar(select(func.count()).select_from(Campaign)),
                s.scalar(select(func.count()).select_from(CampaignMember)),
                sorted((str(c.id), c.status) for c in s.scalars(select(Campaign))),
            )

    before = snapshot()
    api.get(URL, headers=headers[hq])
    for method in (api.post, api.put, api.patch, api.delete):
        assert method(URL, headers=headers[hq]).status_code == 405
    assert snapshot() == before


def test_customers_and_anonymous_are_refused(cal):
    api, cfg, tid, headers, staff, hq = cal
    assert api.get(URL).status_code == 401
    customer = next(u for u in cfg.users if u.role == "customer")
    assert api.get(URL, headers=login(api, cfg.slug, customer.email)).status_code == 403
