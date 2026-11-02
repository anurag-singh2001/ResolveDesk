"""S11.4 GET /growth/brand-signals and the brand job. Runs for every tenant folder, never names one.

Planted data uses a far-future window so seeded history cannot touch the counts.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.models import Brand, Customer, Location, Transaction
from app.core.tenancy import tenant_id_for
from app.modules.growth import brand_signals as bs
from tests.helpers import login

AS_OF = datetime(2041, 1, 10, tzinfo=UTC)
SRC = "s114_plant"


@pytest.fixture
def planted(seeded_history, tenant, app_engine, maint_engine):
    """The first brand's repeat rate falls from 50% to 0%; every other brand holds at 50%.
    Customers are shared across brands, so each brand must count its own repeats."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)

    def clear():
        with tenant_session(tid, maint_engine) as s:
            s.execute(
                delete(Transaction).where(Transaction.tenant_id == tid, Transaction.source == SRC)
            )
            s.execute(
                delete(Customer).where(
                    Customer.tenant_id == tid, Customer.external_ref.like("s114-%")
                )
            )

    clear()
    with tenant_session(tid, maint_engine) as s:
        brands = list(s.scalars(select(Brand).order_by(Brand.slug)))
        locs = list(s.scalars(select(Location).order_by(Location.slug)))
        custs = []
        for i in range(60):
            c = Customer(id=uuid.uuid4(), tenant_id=tid, external_ref=f"s114-{i}", name=f"c{i}")
            s.add(c)
            custs.append(c.id)
        s.flush()
        recent_start = AS_OF - timedelta(days=21)
        base_start = recent_start - timedelta(days=28)
        n = 0

        def order(brand, cust, when):
            nonlocal n
            n += 1
            s.add(
                Transaction(
                    id=uuid.uuid4(),
                    tenant_id=tid,
                    customer_id=cust,
                    brand_id=brand.id,
                    location_id=locs[n % len(locs)].id,  # spread over locations
                    source=SRC,
                    external_ref=f"s114-{n}",
                    placed_at=when,
                    total_paise=10000,
                    status="completed",
                )
            )

        for bi, brand in enumerate(brands):
            for k in range(20):  # baseline: 20 customers x 2 orders = 50% repeat
                order(brand, custs[k], base_start + timedelta(days=1 + k, hours=1))
                order(brand, custs[k], base_start + timedelta(days=3 + k, hours=1))
            if bi == 0:  # recent: 40 different customers, one order each = 0% repeat
                for k in range(40):
                    order(brand, custs[20 + k], recent_start + timedelta(days=k % 20, hours=2))
            else:  # recent: holds at 50%. Fresh customers (no order in this brand in the prior
                # 28 days, else their first recent order would itself count as a repeat).
                for k in range(20):
                    order(brand, custs[20 + k], recent_start + timedelta(days=k % 15, hours=2))
                    order(brand, custs[20 + k], recent_start + timedelta(days=k % 15 + 2, hours=2))
        names = [b.id for b in brands]
    yield tid, names
    clear()


def _read(engine, tid, as_of=AS_OF, brand_ids=frozenset()):
    with tenant_session(tid, engine) as s:
        return bs.brand_readings(s, tid, brand_ids, as_of)


def test_one_brand_drops_while_the_others_hold(planted, app_engine):
    tid, brand_ids = planted
    by_id = {r.brand_id: r for r in _read(app_engine, tid)}
    assert by_id[brand_ids[0]].status == "drop"
    assert by_id[brand_ids[0]].drop_bp == 5000
    for other in brand_ids[1:]:
        assert by_id[other].status == "steady"
        assert by_id[other].drop_bp == 0


def test_a_brand_diagnosis_has_findings_and_hypotheses_from_data(planted, app_engine):
    tid, brand_ids = planted
    with tenant_session(tid, app_engine) as s:
        r = next(x for x in bs.brand_readings(s, tid, frozenset(), AS_OF) if x.flagged)
        d = bs.brand_diagnosis(bs.brand_evidence(s, tid, r))
    assert d.findings and d.hypotheses
    assert any("Repeat-customer rate fell" in f for f in d.findings)
    assert any("New customers were" in f for f in d.findings)


def test_brand_limits_narrow_the_readings(planted, app_engine):
    tid, brand_ids = planted
    one = frozenset({brand_ids[0]})
    assert {r.brand_id for r in _read(app_engine, tid, brand_ids=one)} == one


def test_no_orders_in_the_window_is_low_volume(planted, app_engine):
    tid, _ = planted
    far = AS_OF + timedelta(days=3650)
    assert {r.status for r in _read(app_engine, tid, as_of=far)} == {"low_volume"}


def test_rerunning_gives_the_same_answer(planted, app_engine):
    tid, _ = planted
    assert _read(app_engine, tid) == _read(app_engine, tid)


def _users(cfg, role):
    return [u for u in cfg.users if u.role == role]


def test_needs_a_token(api):
    assert api.get("/growth/brand-signals").status_code == 401


def test_only_hq_gets_brand_signals_everyone_else_gets_404(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    enabled = bool(cfg.feature_flags.get("growth"))
    for user in cfg.users:
        resp = api.get("/growth/brand-signals", headers=login(api, cfg.slug, user.email))
        if user.role == "customer":  # staff-only gate comes first, whatever the flag
            assert resp.status_code == 403, user.email
        elif user.role == "hq_owner" and enabled:
            assert resp.status_code == 200, user.email
        else:  # not HQ, or the growth flag is off (routes are 404 then)
            assert resp.status_code == 404, user.email


def test_hq_sees_its_own_brands_only_with_aggregates_only(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    if not cfg.feature_flags.get("growth"):
        pytest.skip("growth is off for this tenant")
    hq = _users(cfg, "hq_owner")[0]
    body = api.get("/growth/brand-signals", headers=login(api, cfg.slug, hq.email)).json()
    assert body["definition"]
    for b in body["brands"]:
        assert set(b) == {
            "brand_id", "name", "status", "baseline_orders", "recent_orders", "min_orders",
            "baseline_bp", "recent_bp", "drop_bp", "diagnosis",
        }  # fmt: skip
        if b["status"] == "low_volume":  # never a trend on too few orders
            assert b["baseline_bp"] is None and b["drop_bp"] is None and b["diagnosis"] is None
        if b["status"] != "drop":
            assert b["diagnosis"] is None


def test_an_unknown_brand_id_is_404(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    hq = _users(cfg, "hq_owner")[0]
    resp = api.get(
        "/growth/brand-signals",
        params={"brand_id": str(uuid.uuid4())},
        headers=login(api, cfg.slug, hq.email),
    )
    assert resp.status_code == 404


def test_another_tenants_brand_id_is_404(api, seeded_history, tenant, app_engine):
    cfg = seeded_history[tenant.name]
    others = [c for name, c in seeded_history.items() if name != tenant.name]
    if not others:
        pytest.skip("needs a second tenant")
    with tenant_session(tenant_id_for(others[0].slug), app_engine) as s:
        foreign = s.scalars(select(Brand.id)).first()
    hq = _users(cfg, "hq_owner")[0]
    resp = api.get(
        "/growth/brand-signals",
        params={"brand_id": str(foreign)},
        headers=login(api, cfg.slug, hq.email),
    )
    assert resp.status_code == 404
