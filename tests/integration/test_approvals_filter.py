"""GET /approvals filters and sorts (S5.4), for every tenant, never naming one.

Four pending proposals (three refunds of different sizes, one voucher) are created on separate
orders at one location, one transaction each so their created_at values differ. A second,
empty location is added so "another outlet" exists even for a single-location tenant.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.models import Case, Location, Transaction
from app.core.tenancy import tenant_id_for
from app.engine.eligibility import order_facts
from app.engine.proposals import create_proposal
from tests.helpers import login


def _users(cfg, role):
    return [u for u in cfg.users if u.role == role]


@pytest.fixture
def queue(api, app_engine, maint_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    hq = login(api, cfg.slug, _users(cfg, "hq_owner")[0].email)
    managers = _users(cfg, "location_manager")
    if not managers:
        pytest.skip("this tenant has no location_manager")
    mgr = login(api, cfg.slug, managers[0].email)
    own_loc = uuid.UUID(api.get("/me", headers=mgr).json()["location_ids"][0])
    extra_loc = uuid.uuid4()
    with tenant_session(tid, maint_engine) as s:
        s.add(
            Location(id=extra_loc, tenant_id=tid, slug=f"s54-{extra_loc.hex[:8]}", name="S54 empty")
        )
    with tenant_session(tid, app_engine) as s:
        orders = s.scalars(
            select(Transaction)
            .where(Transaction.location_id == own_loc, Transaction.total_paise >= 1000)
            .order_by(Transaction.id)
            .limit(4)
        ).all()
        if len(orders) < 4:
            pytest.skip("not enough orders at the manager's location")
        order_ids = [o.id for o in orders]
        customers = [o.customer_id for o in orders]
        voucher_paise = order_facts(s, order_ids[3])[1].settings["voucher_auto_approve_max_paise"]
    plan = [
        ("refund", {"amount_paise": 200}),
        ("refund", {"amount_paise": 500}),
        ("free_item_voucher", {"value_paise": voucher_paise}),
        ("refund", {"amount_paise": 100}),
    ]
    case_ids, proposals = [], []
    for oid, cust, (action, extra) in zip(order_ids, customers, plan, strict=True):
        cid = uuid.uuid4()
        with tenant_session(tid, app_engine) as s:  # own transaction: distinct created_at
            s.add(
                Case(
                    id=cid,
                    tenant_id=tid,
                    customer_id=cust,
                    transaction_id=oid,
                    status="awaiting_approval",
                    channel="app",
                    opened_at=datetime.now(UTC),
                )
            )
            s.flush()
            params = {"transaction_id": str(oid), "reason": "x", **extra}
            proposals.append(
                create_proposal(s, tid, case_id=cid, action=action, reason="p", params=params).id
            )
        case_ids.append(cid)
    yield {
        "api": api,
        "cfg": cfg,
        "hq": hq,
        "mgr": mgr,
        "own_loc": str(own_loc),
        "extra_loc": str(extra_loc),
        "mine": {str(p) for p in proposals},
        "ordered": [str(p) for p in proposals],  # creation order, oldest first
        "voucher": str(proposals[2]),
        "seeded": seeded_history,
        "tenant_name": tenant.name,
    }
    with tenant_session(tid, maint_engine) as s:
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id.in_(case_ids)))
        s.execute(delete(Location).where(Location.tenant_id == tid, Location.id == extra_loc))


def _get(q, headers, **params):
    return q["api"].get("/approvals", headers=headers, params=params)


def _mine(q, resp):
    assert resp.status_code == 200, resp.text
    return [p for p in resp.json() if p["proposal_id"] in q["mine"]]


def test_default_is_oldest_first(queue):
    rows = _mine(queue, _get(queue, queue["hq"]))
    assert [r["proposal_id"] for r in rows] == queue["ordered"]
    assert [r["proposal_id"] for r in _mine(queue, _get(queue, queue["hq"], sort="oldest"))] == (
        queue["ordered"]
    )


def test_newest_reverses_oldest(queue):
    rows = _mine(queue, _get(queue, queue["hq"], sort="newest"))
    assert [r["proposal_id"] for r in rows] == list(reversed(queue["ordered"]))


def test_amount_desc_is_largest_first(queue):
    amounts = [
        r["amount_paise"] for r in _mine(queue, _get(queue, queue["hq"], sort="amount_desc"))
    ]
    assert len(amounts) == 4
    assert amounts == sorted(amounts, reverse=True)
    assert amounts[0] >= 500


def test_location_filter_only_returns_that_location(queue):
    rows = _mine(queue, _get(queue, queue["hq"], location_id=queue["own_loc"]))
    assert {r["proposal_id"] for r in rows} == queue["mine"]
    all_hq = _get(queue, queue["hq"], location_id=queue["own_loc"]).json()
    assert len({r["location_name"] for r in all_hq}) == 1
    # Another (empty) outlet of the same tenant: visible to HQ, nothing pending there.
    empty = _get(queue, queue["hq"], location_id=queue["extra_loc"])
    assert empty.status_code == 200 and empty.json() == []


def test_action_filter(queue):
    rows = _mine(queue, _get(queue, queue["hq"], action="free_item_voucher"))
    assert [r["proposal_id"] for r in rows] == [queue["voucher"]]
    refunds = _mine(queue, _get(queue, queue["hq"], action="refund"))
    assert len(refunds) == 3 and {r["action"] for r in refunds} == {"refund"}
    assert _get(queue, queue["hq"], action="no_such_action").status_code == 422


def test_out_of_scope_location_is_404_for_a_location_manager(queue):
    own = _mine(queue, _get(queue, queue["mgr"], location_id=queue["own_loc"]))
    assert {r["proposal_id"] for r in own} == queue["mine"]
    assert _get(queue, queue["mgr"], location_id=queue["extra_loc"]).status_code == 404
    assert _get(queue, queue["mgr"], location_id=str(uuid.uuid4())).status_code == 404


def test_unknown_sort_is_422(queue):
    assert _get(queue, queue["hq"], sort="sideways").status_code == 422


def test_another_tenants_location_is_404(queue, app_engine):
    others = [c for name, c in queue["seeded"].items() if name != queue["tenant_name"]]
    assert others, "needs a second tenant"
    other_tid = tenant_id_for(others[0].slug)
    with tenant_session(other_tid, app_engine) as s:
        foreign = s.scalar(select(Location.id).order_by(Location.id).limit(1))
    assert foreign is not None
    for headers in (queue["hq"], queue["mgr"]):
        assert _get(queue, headers, location_id=str(foreign)).status_code == 404
