"""S11.2 segments and cohorts: role scope, 404s, consent counting, small cells, the shared
"lapsed" rule and pinned SEED=42 counts. UNRUN when written (no database was available): the
golden file tests/integration/golden/segments_seed42.json starts empty and is filled by one real
run with UPDATE_GOLDEN=1.

Runs for every tenant folder and never names one: scope comes from each user's role, and the
rows a test needs it creates itself and removes afterwards.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from app.core.db import tenant_session
from app.core.models import Consent, Customer, LocationBrand, TenantSetting, Transaction
from app.core.settings_resolver import effective_settings
from app.core.tenancy import tenant_id_for
from app.modules.growth import campaigns as camp
from app.modules.growth.signals import data_as_of
from tests.helpers import login

SEG = "/insights/segments"
COH = "/insights/cohorts"
GOLDEN = Path(__file__).parent / "golden" / "segments_seed42.json"
FORBIDDEN_KEYS = {"customer_id", "customer_ids", "phone", "email", "customer", "members"}
SETTING_KEYS = ("small_cell_min", "lapsed_days")


def _users(cfg, role):
    return [u for u in cfg.users if u.role == role]


def _hdr(api, cfg, role):
    users = _users(cfg, role)
    if not users:
        pytest.skip(f"this tenant has no {role}")
    return login(api, cfg.slug, users[0].email)


def _all_group(body):
    return next(g for g in body["groups"] if g["id"] is None)


def _cell(group, name):
    return next(c for c in group["segments"] if c["segment"] == name)


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def _at(api, headers, loc, url=SEG):
    resp = api.get(url, params={"location_id": str(loc)}, headers=headers)
    assert resp.status_code == 200, resp.text
    return _all_group(resp.json())


def test_needs_a_token_and_refuses_customers(api, seeded_history, tenant):
    assert api.get(SEG).status_code == 401 and api.get(COH).status_code == 401
    cfg = seeded_history[tenant.name]
    for user in _users(cfg, "customer")[:1]:
        headers = login(api, cfg.slug, user.email)
        assert api.get(SEG, headers=headers).status_code == 403
        assert api.get(COH, headers=headers).status_code == 403


def test_works_whatever_the_growth_flag_says(api, seeded_history, tenant):
    # Read-only analytics: not behind the `growth` flag, so every tenant answers.
    cfg = seeded_history[tenant.name]
    hq = _hdr(api, cfg, "hq_owner")
    assert api.get(SEG, headers=hq).status_code == 200
    assert api.get(COH, headers=hq).status_code == 200


def test_aggregates_only_and_integer_money(api, seeded_history, tenant, maint_engine):
    cfg = seeded_history[tenant.name]
    hq = _hdr(api, cfg, "hq_owner")
    with tenant_session(tenant_id_for(cfg.slug), maint_engine) as s:
        phones = [p for p in s.scalars(select(Customer.phone).limit(200)) if p]
        refs = list(s.scalars(select(Customer.external_ref).limit(200)))
    for url in (SEG, COH):
        resp = api.get(url, headers=hq)
        assert resp.status_code == 200
        assert not (set(_keys(resp.json())) & FORBIDDEN_KEYS)
        assert not any(p in resp.text for p in phones)
        assert not any(r in resp.text for r in refs)
    for group in api.get(SEG, headers=hq).json()["groups"]:
        for c in group["segments"]:
            for key in ("total_spend_paise", "aov_paise", "in_segment", "share_bp"):
                assert c[key] is None or type(c[key]) is int
            assert not c["suppressed"]  # hq sees every cell
            assert c["contactable_whatsapp"] <= c["in_segment"]
            assert c["aggregator_only_not_contactable"] <= c["aggregator_only"]
            assert c["own_channel"] + c["aggregator_only"] == c["in_segment"]


def test_active_plus_lapsed_is_everyone(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    body = api.get(SEG, headers=_hdr(api, cfg, "hq_owner")).json()
    for group in body["groups"]:
        n = {c["segment"]: c["in_segment"] for c in group["segments"]}
        assert n["active"] + n["lapsed"] == group["customers"]
        assert n["lapsed_regular"] <= n["lapsed"]
        assert n["loyal"] <= n["active"] and n["at_risk"] <= n["active"]


def test_scope_by_role_and_404s(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    hq = _hdr(api, cfg, "hq_owner")
    everything = {x["id"] for x in api.get("/locations", headers=hq).json()}
    for url in (SEG, COH):
        for param in ("location_id", "brand_id"):
            resp = api.get(url, params={param: str(uuid.uuid4())}, headers=hq)
            assert resp.status_code == 404
    for role in ("franchisee_owner", "location_manager"):
        for user in _users(cfg, role):
            headers = login(api, cfg.slug, user.email)
            own = set(api.get("/me", headers=headers).json()["location_ids"])
            for lid in everything - own:  # someone else's outlet: absent, not forbidden
                for url in (SEG, COH):
                    r = api.get(url, params={"location_id": lid}, headers=headers)
                    assert r.status_code == 404, (role, user.email)
            for lid in own:  # their own outlet equals what HQ sees for it (small cells aside)
                mine, full = _at(api, headers, lid), _at(api, hq, lid)
                assert mine["customers"] in (None, full["customers"])
                for a, b in zip(mine["segments"], full["segments"], strict=True):
                    assert a["suppressed"] or a["in_segment"] == b["in_segment"]


def test_brand_limited_caller_cannot_widen_by_brand_id(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    hq = _hdr(api, cfg, "hq_owner")
    all_brands = {g["id"] for g in api.get(SEG, headers=hq).json()["groups"] if g["id"]}
    for user in _users(cfg, "franchisee_owner"):
        headers = login(api, cfg.slug, user.email)
        mine = set(api.get("/me", headers=headers).json().get("brand_ids") or [])
        if not mine:
            continue
        seen = {g["id"] for g in api.get(SEG, headers=headers).json()["groups"] if g["id"]}
        assert seen == mine & all_brands
        for other in all_brands - mine:
            assert api.get(SEG, params={"brand_id": other}, headers=headers).status_code == 404


# -- rows the tests plant ------------------------------------------------------------------------


@pytest.fixture
def planted(seeded_history, tenant, maint_engine):
    """Adds customers, orders and consents at one location, timed at the newest order (so the
    data's "as of" does not move), and removes them and any setting override afterwards."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    made: list[uuid.UUID] = []

    def plant(loc, brand, source="own_app", phone="9000000000", consent=None, days_before=0):
        """consent: None = no row, True = granted, False = not granted (withdrawn)."""
        with tenant_session(tid, maint_engine) as s:
            newest = s.scalar(
                select(func.max(Transaction.placed_at)).where(Transaction.tenant_id == tid)
            )
            cid = uuid.uuid4()
            s.add(
                Customer(id=cid, tenant_id=tid, external_ref=f"seg-{cid}", name="Seg Test",
                         phone=phone, home_location_id=loc)
            )  # fmt: skip
            s.flush()
            s.add(
                Transaction(id=uuid.uuid4(), tenant_id=tid, customer_id=cid, brand_id=brand,
                            location_id=loc, source=source, external_ref=f"seg-{cid}",
                            placed_at=newest - timedelta(days=days_before), total_paise=10000,
                            status="completed", attributes={})
            )  # fmt: skip
            if consent is not None:
                s.add(
                    Consent(tenant_id=tid, customer_id=cid, channel="whatsapp",
                            purpose="marketing", granted=consent)
                )  # fmt: skip
        made.append(cid)
        return cid

    yield cfg, tid, plant
    with tenant_session(tid, maint_engine) as s:
        s.execute(delete(Transaction).where(Transaction.customer_id.in_(made)))
        s.execute(delete(Consent).where(Consent.customer_id.in_(made)))
        s.execute(delete(Customer).where(Customer.id.in_(made)))
        s.execute(delete(TenantSetting).where(TenantSetting.key.in_(SETTING_KEYS)))


def _override(engine, tid, key, value):
    with tenant_session(tid, engine) as s:
        s.execute(delete(TenantSetting).where(TenantSetting.key == key))
        s.add(TenantSetting(tenant_id=tid, key=key, value=value))


def _a_location_and_brand(engine, tid):
    with tenant_session(tid, engine) as s:
        row = s.execute(select(LocationBrand.location_id, LocationBrand.brand_id).limit(1)).one()
    return row.location_id, row.brand_id


def _scoped_headers_at(api, cfg, loc):
    for u in cfg.users:
        if u.role in ("location_manager", "franchisee_owner"):
            headers = login(api, cfg.slug, u.email)
            if str(loc) in api.get("/me", headers=headers).json()["location_ids"]:
                return headers
    pytest.skip("no scoped user at that outlet")


def test_consent_counts_never_leak_into_the_in_segment_number(api, planted, maint_engine):
    cfg, tid, plant = planted
    hq = _hdr(api, cfg, "hq_owner")
    loc, brand = _a_location_and_brand(maint_engine, tid)
    before = _cell(_at(api, hq, loc), "new")
    plant(loc, brand, phone="9100000001", consent=None)  # no consent row
    plant(loc, brand, phone="9100000002", consent=False)  # granted, then withdrawn
    plant(loc, brand, phone="9100000003", consent=True)  # contactable
    plant(loc, brand, phone="9100000003", consent=True)  # same phone: one contact only
    plant(loc, brand, phone="", consent=True)  # consent but no phone
    after = _cell(_at(api, hq, loc), "new")
    assert after["in_segment"] - before["in_segment"] == 5
    assert after["contactable_whatsapp"] - before["contactable_whatsapp"] == 1


def test_withdrawal_after_a_grant_removes_the_contact(api, planted, maint_engine):
    cfg, tid, plant = planted
    hq = _hdr(api, cfg, "hq_owner")
    loc, brand = _a_location_and_brand(maint_engine, tid)
    cid = plant(loc, brand, phone="9100000009", consent=True)
    granted = _cell(_at(api, hq, loc), "new")["contactable_whatsapp"]
    with tenant_session(tid, maint_engine) as s:
        s.scalar(select(Consent).where(Consent.customer_id == cid)).granted = False
    assert _cell(_at(api, hq, loc), "new")["contactable_whatsapp"] == granted - 1


def test_aggregator_only_customers_are_split_out_and_flagged(api, planted, maint_engine):
    cfg, tid, plant = planted
    with tenant_session(tid, maint_engine) as s:
        sources = effective_settings(s).get("aggregator_order_sources") or []
    if not sources:
        pytest.skip("this tenant configures no aggregator sources")
    hq = _hdr(api, cfg, "hq_owner")
    loc, brand = _a_location_and_brand(maint_engine, tid)
    before = _cell(_at(api, hq, loc), "new")
    plant(loc, brand, source=sources[0], phone="9100000011", consent=None)
    plant(loc, brand, source=sources[0], phone="9100000012", consent=True)
    plant(loc, brand, source="own_app", phone="9100000013", consent=None)
    after = _cell(_at(api, hq, loc), "new")
    assert after["aggregator_only"] - before["aggregator_only"] == 2
    assert after["aggregator_only_not_contactable"] - before["aggregator_only_not_contactable"] == 1
    assert after["own_channel"] - before["own_channel"] == 1


def test_small_cells_are_hidden_for_non_hq_only(api, planted, maint_engine):
    cfg, tid, plant = planted
    hq = _hdr(api, cfg, "hq_owner")
    loc, brand = _a_location_and_brand(maint_engine, tid)
    for i in range(3):
        plant(loc, brand, phone=f"92000000{i:02d}")
    size = _cell(_at(api, hq, loc), "new")["in_segment"]
    assert size >= 3
    scoped = _scoped_headers_at(api, cfg, loc)

    _override(maint_engine, tid, "small_cell_min", size)  # exactly at the minimum: shown, unless
    seg = _cell(_at(api, scoped, loc), "new")  # a small brand cell forces a sibling hidden
    brand_sizes = [
        _cell(g, "new")["in_segment"]
        for g in api.get(SEG, params={"location_id": str(loc)}, headers=hq).json()["groups"]
    ]
    if min(brand_sizes) >= size:
        assert not seg["suppressed"] and seg["in_segment"] == size
    elif not seg["suppressed"]:
        assert seg["in_segment"] == size

    _override(maint_engine, tid, "small_cell_min", size + 1)  # one below: hidden, nothing leaks
    seg = _cell(_at(api, scoped, loc), "new")
    assert seg["suppressed"]
    assert all(v is None for k, v in seg.items() if k not in ("segment", "suppressed"))
    top = _cell(_at(api, hq, loc), "new")
    assert not top["suppressed"] and top["in_segment"] == size


def test_small_cohorts_are_hidden_for_non_hq_only(api, planted, maint_engine):
    cfg, tid, plant = planted
    hq = _hdr(api, cfg, "hq_owner")
    loc, brand = _a_location_and_brand(maint_engine, tid)
    for i in range(3):
        plant(loc, brand, phone=f"93000000{i:02d}")
    full = _at(api, hq, loc, COH)
    assert len(full["cohorts"]) == 6 and not any(r["suppressed"] for r in full["cohorts"])
    # The planted customers sit in the month of the newest order. The final row is the month of
    # "as of" (local midnight after it), which is a still-empty month when that order falls on
    # the last day of a month, so take the last cohort that has anyone in it.
    at = max(i for i, r in enumerate(full["cohorts"]) if r["size"])
    newest = full["cohorts"][at]["size"]
    assert newest >= 3
    scoped = _scoped_headers_at(api, cfg, loc)
    _override(maint_engine, tid, "small_cell_min", newest + 1)
    rows = _at(api, scoped, loc, COH)["cohorts"]
    assert rows[at]["suppressed"] and rows[at]["size"] is None and rows[at]["cells"] == []
    assert all(r["suppressed"] or r["size"] >= newest + 1 for r in rows)
    assert not _at(api, hq, loc, COH)["cohorts"][at]["suppressed"]


def test_cohort_cells_are_months_after_first_order_and_never_ahead_of_the_data(
    api, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    for group in api.get(COH, headers=_hdr(api, cfg, "hq_owner")).json()["groups"]:
        assert len(group["cohorts"]) == 6
        for row in group["cohorts"]:
            assert [c["month"] for c in row["cells"]] == [1, 2, 3]
            for c in row["cells"]:
                if c["measurable"]:
                    assert 0 <= c["returned"] <= row["size"]
                    assert c["return_bp"] is None or 0 <= c["return_bp"] <= 10000
                else:
                    assert c["returned"] is None and c["return_bp"] is None
        assert not group["cohorts"][-1]["cells"][0]["measurable"]  # this month is not over


# -- one meaning of "lapsed", and the audience's consent clauses ---------------------------------


def test_lapsed_audience_keeps_its_consent_clauses_and_agrees_with_the_segment(
    api, planted, app_engine, maint_engine
):
    cfg, tid, plant = planted
    loc, brand = _a_location_and_brand(maint_engine, tid)
    old = camp.LAPSED_DAYS + 5  # days before the newest order: well past the cut-off
    no_consent = plant(loc, brand, phone="9400000001", consent=None, days_before=old)
    withdrawn = plant(loc, brand, phone="9400000002", consent=False, days_before=old)
    good = plant(loc, brand, phone="9400000003", consent=True, days_before=old)
    twin = plant(loc, brand, phone="9400000003", consent=True, days_before=old)
    no_phone = plant(loc, brand, phone="", consent=True, days_before=old)
    with tenant_session(tid, app_engine) as s:
        as_of = data_as_of(s, tid, datetime.now(UTC))
        audience = {c for c, _ in camp.lapsed_audience(s, tid, loc, as_of)}
    assert len(audience & {good, twin}) == 1  # one customer per phone, never both
    assert not (audience & {no_consent, withdrawn, no_phone})
    # The segment's contactable lapsed count is the same set (no campaign has run here).
    hq = _hdr(api, cfg, "hq_owner")
    assert _cell(_at(api, hq, loc), "lapsed")["contactable_whatsapp"] == len(audience)


def test_changing_lapsed_days_moves_the_audience_and_the_segment_together(
    api, planted, app_engine, maint_engine
):
    cfg, tid, plant = planted
    loc, brand = _a_location_and_brand(maint_engine, tid)
    plant(loc, brand, phone="9400000010", consent=True, days_before=40)
    hq = _hdr(api, cfg, "hq_owner")
    for days in (28, 3650):
        _override(maint_engine, tid, "lapsed_days", days)
        with tenant_session(tid, app_engine) as s:
            as_of = data_as_of(s, tid, datetime.now(UTC))
            audience = camp.lapsed_audience(s, tid, loc, as_of, days)
        group = _at(api, hq, loc)
        assert api.get(SEG, headers=hq).json()["lapsed_days"] == days
        assert _cell(group, "lapsed")["contactable_whatsapp"] == len(audience)


# -- pinned counts -------------------------------------------------------------------------------


def _snapshot(seg_body, coh_body):
    return {
        "customers": [g["customers"] for g in seg_body["groups"]],
        "segments": {
            g["name"]: {c["segment"]: c["in_segment"] for c in g["segments"]}
            for g in seg_body["groups"]
        },
        "contactable": {
            g["name"]: {c["segment"]: c["contactable_whatsapp"] for c in g["segments"]}
            for g in seg_body["groups"]
        },
        "cohort_sizes": {g["name"]: [r["size"] for r in g["cohorts"]] for g in coh_body["groups"]},
    }


def test_counts_are_deterministic_and_pinned_for_seed_42(api, seeded_history, tenant):
    """Fill the golden file with one real run: UPDATE_GOLDEN=1 pytest -k pinned_for_seed_42.
    Until then this fails on purpose (an unpinned test pins nothing). The history is generated at
    the fixture's HISTORY_SCALE, so the numbers belong to that scale."""
    cfg = seeded_history[tenant.name]
    hq = _hdr(api, cfg, "hq_owner")
    first = _snapshot(api.get(SEG, headers=hq).json(), api.get(COH, headers=hq).json())
    second = _snapshot(api.get(SEG, headers=hq).json(), api.get(COH, headers=hq).json())
    assert first == second  # deterministic for the same data
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden[cfg.slug] = first
        GOLDEN.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert cfg.slug in golden, "golden counts not recorded yet: run once with UPDATE_GOLDEN=1"
    assert first == golden[cfg.slug]


# -- a hidden number cannot be worked out from the rest of the response --------------------------


def _unsolvable(body, kind):
    """No relation (total = active + lapsed in a group; all brands vs the others for each cell)
    has exactly one hidden term, so a reader cannot compute a hidden number. UNRUN."""
    groups = body["groups"]
    if kind == "segments":
        per = [
            {"customers": g["customers"], **{c["segment"]: c["in_segment"] for c in g["segments"]}}
            for g in groups
        ]
        for p in per:
            hidden = [p[k] is None for k in ("customers", "active", "lapsed")]
            assert sum(hidden) != 1, p
        names = list(per[0])
    else:
        per = [{r["cohort_month"]: r["size"] for r in g["cohorts"]} for g in groups]
        names = list(per[0])
    if len(per) > 1:
        for n in names:
            assert sum(p[n] is None for p in per) != 1, n


def test_hidden_cells_cannot_be_derived_from_the_response(api, planted, maint_engine):
    cfg, tid, plant = planted
    loc, brand = _a_location_and_brand(maint_engine, tid)
    for i in range(4):
        plant(loc, brand, phone=f"95000000{i:02d}")
    scoped = _scoped_headers_at(api, cfg, loc)
    for minimum in (2, 5, 20, 80, 10**6):
        _override(maint_engine, tid, "small_cell_min", minimum)
        for params in ({}, {"location_id": str(loc)}):
            for url, kind in ((SEG, "segments"), (COH, "cohorts")):
                resp = api.get(url, params=params, headers=scoped)
                assert resp.status_code == 200
                _unsolvable(resp.json(), kind)
