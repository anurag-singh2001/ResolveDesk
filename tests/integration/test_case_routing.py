"""S7.2 routing by hierarchy + S7.3 "Cases to handle" queue, for every tenant, never naming one.

Expected owners come from the tenant folder's users (their role and outlets), not from the
code under test. A second, staff-less outlet is created and one order moved onto it, so the
"no manager, no franchisee -> HQ" and "another outlet" cases exist for every tenant.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, update

from app.core.db import tenant_session
from app.core.models import AuditEvent, Case, Location, Transaction, User
from app.core.settings_resolver import effective_settings
from app.core.tenancy import tenant_id_for
from app.engine import lifecycle
from app.engine.proposals import create_proposal
from tests.helpers import login


def _staff(cfg, role):
    return [u for u in cfg.users if u.role == role]


@pytest.fixture
def world(api, app_engine, maint_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    extra_loc = uuid.uuid4()
    with tenant_session(tid, maint_engine) as s:
        s.add(
            Location(id=extra_loc, tenant_id=tid, slug=f"s72-{extra_loc.hex[:8]}", name="S72 bare")
        )
    with tenant_session(tid, app_engine) as s:
        locs = {slug: lid for lid, slug in s.execute(select(Location.id, Location.slug)).all()}
        ids = {e: i for i, e in s.execute(select(User.id, User.email)).all()}
        limit = effective_settings(s)["refund_without_escalation_paise"]
        by_loc: dict[uuid.UUID, uuid.UUID] = {}
        for loc_id in locs.values():
            order = s.scalar(
                select(Transaction)
                .where(Transaction.location_id == loc_id, Transaction.total_paise >= 1000)
                .order_by(Transaction.id)
            )
            if order is not None:
                by_loc[loc_id] = order.id
        spare = s.scalar(
            select(Transaction)
            .where(~Transaction.id.in_(by_loc.values()), Transaction.total_paise >= 1000)
            .order_by(Transaction.id)
        )
        orders = {k: s.get(Transaction, v) for k, v in by_loc.items()}
        customers = {k: o.customer_id for k, o in orders.items()}
        spare_id, spare_loc, spare_cust = spare.id, spare.location_id, spare.customer_id
    # The spare order lives at the staff-less outlet while the test runs.
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            update(Transaction).where(Transaction.id == spare_id).values(location_id=extra_loc)
        )
    cases: list[uuid.UUID] = []
    w = {
        "api": api,
        "cfg": cfg,
        "tid": tid,
        "engine": app_engine,
        "locs": locs,
        "ids": ids,
        "limit": limit,
        "order_at": by_loc,
        "cust_at": customers,
        "extra_loc": extra_loc,
        "spare": (spare_id, spare_cust),
        "cases": cases,
    }
    yield w
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            update(Transaction).where(Transaction.id == spare_id).values(location_id=spare_loc)
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id.in_(cases)))
        s.execute(delete(Location).where(Location.id == extra_loc))


def _new_case(w, order_id, customer_id, status="investigating") -> uuid.UUID:
    cid = uuid.uuid4()
    with tenant_session(w["tid"], w["engine"]) as s:
        s.add(
            Case(
                id=cid,
                tenant_id=w["tid"],
                customer_id=customer_id,
                transaction_id=order_id,
                status=status,
                channel="app",
                opened_at=datetime.now(UTC),
            )
        )
    w["cases"].append(cid)
    return cid


def _escalate(w, order_id, customer_id) -> uuid.UUID:
    cid = _new_case(w, order_id, customer_id)
    lifecycle.escalate(w["engine"], w["tid"], cid, "test escalation")
    return cid


def _owner(w, cid):
    with tenant_session(w["tid"], w["engine"]) as s:
        return s.get(Case, cid).owner_user_id


def _expected(w, loc_slug):
    """Owner per the tenant folder: lowest-id manager of the outlet, else franchisee, else HQ."""
    cfg = w["cfg"]
    for role in ("location_manager", "franchisee_owner"):
        found = [w["ids"][u.email] for u in _staff(cfg, role) if loc_slug in u.locations]
        if found:
            return min(found)
    return min(w["ids"][u.email] for u in _staff(cfg, "hq_owner"))


def test_escalation_assigns_the_outlet_staff(world):
    w = world
    checked = 0
    for slug, loc_id in w["locs"].items():
        if loc_id not in w["order_at"]:
            continue
        cid = _escalate(w, w["order_at"][loc_id], w["cust_at"][loc_id])
        assert _owner(w, cid) == _expected(w, slug), slug
        checked += 1
    assert checked >= 1


def test_outlet_without_staff_goes_to_hq(world):
    w = world
    order_id, cust = w["spare"]
    cid = _escalate(w, order_id, cust)
    hq = min(w["ids"][u.email] for u in _staff(w["cfg"], "hq_owner"))
    assert _owner(w, cid) == hq


def test_case_without_an_order_goes_to_hq(world):
    w = world
    any_cust = next(iter(w["cust_at"].values()))
    cid = _escalate(w, None, any_cust)
    hq = min(w["ids"][u.email] for u in _staff(w["cfg"], "hq_owner"))
    assert _owner(w, cid) == hq


def _pending_refund(w, loc_id, paise) -> uuid.UUID:
    order_id = w["order_at"][loc_id]
    cid = _new_case(w, order_id, w["cust_at"][loc_id], status="open")
    with tenant_session(w["tid"], w["engine"]) as s:
        proposal = create_proposal(
            s,
            w["tid"],
            case_id=cid,
            action="refund",
            reason="p",
            params={"transaction_id": str(order_id), "reason": "x", "amount_paise": paise},
        )
        s.flush()
        case = s.get(Case, cid)
        lifecycle.proposal_made(s, w["tid"], case, proposal.id, datetime.now(UTC))
    return cid


def test_amount_above_the_limit_goes_to_hq(world):
    w = world
    loc_id, slug = next((i, s) for s, i in w["locs"].items() if i in w["order_at"])
    big = _pending_refund(w, loc_id, w["limit"] + 1)
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.get(Case, big).status == "awaiting_approval"
    hq = min(w["ids"][u.email] for u in _staff(w["cfg"], "hq_owner"))
    assert _owner(w, big) == hq
    small = _pending_refund(w, loc_id, 1)
    with tenant_session(w["tid"], w["engine"]) as s:
        status = s.get(Case, small).status
    if status == "awaiting_approval":  # an auto-approved refund needs nobody
        assert _owner(w, small) == _expected(w, slug)
    else:
        assert _owner(w, small) is None


def test_existing_owner_is_kept(world):
    w = world
    loc_id = next(i for i in w["locs"].values() if i in w["order_at"])
    cid = _new_case(w, w["order_at"][loc_id], w["cust_at"][loc_id], status="escalated")
    someone = w["ids"][_staff(w["cfg"], "hq_owner")[0].email]
    with tenant_session(w["tid"], w["engine"]) as s:
        s.get(Case, cid).owner_user_id = someone
    lifecycle.escalate(w["engine"], w["tid"], cid, "again")  # already escalated: no-op
    assert _owner(w, cid) == someone


def _queue(w, headers, **params):
    resp = w["api"].get("/cases/queue", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mine(w, rows):
    return [r for r in rows if uuid.UUID(r["case_id"]) in w["cases"]]


def test_queue_scope_per_role(world):
    w = world
    expected_loc: dict[uuid.UUID, str] = {}
    for slug, loc_id in w["locs"].items():
        if loc_id in w["order_at"]:
            expected_loc[_escalate(w, w["order_at"][loc_id], w["cust_at"][loc_id])] = slug
    order_id, cust = w["spare"]
    expected_loc[_escalate(w, order_id, cust)] = "<bare>"
    for user in w["cfg"].users:
        if user.role == "customer":
            continue
        rows = _mine(w, _queue(w, login(w["api"], w["cfg"].slug, user.email)))
        got = {uuid.UUID(r["case_id"]) for r in rows}
        if user.role == "hq_owner":
            want = set(expected_loc)
        else:
            want = {c for c, slug in expected_loc.items() if slug in user.locations}
        assert got == want, user.email
    customer = next(u for u in w["cfg"].users if u.role == "customer")
    headers = login(w["api"], w["cfg"].slug, customer.email)
    assert w["api"].get("/cases/queue", headers=headers).status_code == 403


def test_queue_rows_filters_and_order(world):
    w = world
    loc_id = next(i for i in w["locs"].values() if i in w["order_at"])
    first = _escalate(w, w["order_at"][loc_id], w["cust_at"][loc_id])
    pending = _pending_refund(w, loc_id, w["limit"] + 1)
    second = _escalate(w, w["order_at"][loc_id], w["cust_at"][loc_id])
    hq = _staff(w["cfg"], "hq_owner")[0]
    headers = login(w["api"], w["cfg"].slug, hq.email)
    rows = _mine(w, _queue(w, headers))
    order = [uuid.UUID(r["case_id"]) for r in rows]
    assert order == [first, pending, second]  # oldest wait first
    by_id = {uuid.UUID(r["case_id"]): r for r in rows}
    assert by_id[first]["reason_kind"] == "escalated"
    assert by_id[first]["reason"] == "test escalation"
    assert by_id[first]["waiting_seconds"] >= 0 and by_id[first]["language"]
    assert by_id[pending]["reason_kind"] == "awaiting_approval"
    assert by_id[pending]["amount_paise"] == w["limit"] + 1
    assert by_id[pending]["proposal_id"]
    assert by_id[pending]["owner_name"] == hq.name and by_id[pending]["owned_by_me"] is (
        w["ids"][hq.email] == min(w["ids"][u.email] for u in _staff(w["cfg"], "hq_owner"))
    )
    only = _mine(w, _queue(w, headers, reason="awaiting_approval"))
    assert [uuid.UUID(r["case_id"]) for r in only] == [pending]
    assert _mine(w, _queue(w, headers, category="no_such_category")) == []
    assert w["api"].get("/cases/queue", headers=headers, params={"reason": "x"}).status_code == 422
    mine = {uuid.UUID(r["case_id"]) for r in _mine(w, _queue(w, headers, owned_by_me=True))}
    assert pending in mine or w["ids"][hq.email] != _owner(w, pending)


def _reassign(w, headers, cid, user_id):
    return w["api"].post(f"/cases/{cid}/owner", headers=headers, json={"user_id": str(user_id)})


def test_hq_can_reassign_and_it_is_audited(world):
    w = world
    loc_id = next(i for i in w["locs"].values() if i in w["order_at"])
    cid = _escalate(w, w["order_at"][loc_id], w["cust_at"][loc_id])
    hq_users = _staff(w["cfg"], "hq_owner")
    headers = login(w["api"], w["cfg"].slug, hq_users[0].email)
    target = w["ids"][hq_users[0].email]
    resp = _reassign(w, headers, cid, target)
    assert resp.status_code == 200, resp.text
    assert _owner(w, cid) == target
    with tenant_session(w["tid"], w["engine"]) as s:
        actors = s.scalars(
            select(AuditEvent.actor_id).where(
                AuditEvent.entity_id == cid, AuditEvent.event == "case.owner_changed"
            )
        ).all()
    assert actors == [str(target)]


def test_reassign_target_rules(world):
    w = world
    loc_id = next(i for i in w["locs"].values() if i in w["order_at"])
    cid = _escalate(w, w["order_at"][loc_id], w["cust_at"][loc_id])
    hq = _staff(w["cfg"], "hq_owner")[0]
    headers = login(w["api"], w["cfg"].slug, hq.email)
    customer = next(u for u in w["cfg"].users if u.role == "customer")
    assert _reassign(w, headers, cid, w["ids"][customer.email]).status_code == 422
    assert _reassign(w, headers, cid, uuid.uuid4()).status_code == 422
    # A scoped staff member cannot own a case at an outlet they cannot see.
    order_id, cust = w["spare"]
    bare = _escalate(w, order_id, cust)
    scoped = next(u for u in w["cfg"].users if u.locations and u.role != "hq_owner")
    assert _reassign(w, headers, bare, w["ids"][scoped.email]).status_code == 422
    # A case that needs nobody cannot be assigned.
    done = _new_case(w, w["order_at"][loc_id], w["cust_at"][loc_id], status="resolved")
    assert _reassign(w, headers, done, w["ids"][hq.email]).status_code == 409


def test_manager_cannot_reassign_or_see_other_outlets(world):
    w = world
    managers = _staff(w["cfg"], "location_manager")
    if not managers:
        pytest.skip("this tenant has no location_manager")
    mgr = managers[0]
    headers = login(w["api"], w["cfg"].slug, mgr.email)
    own = next(i for s, i in w["locs"].items() if s in mgr.locations and i in w["order_at"])
    mine = _escalate(w, w["order_at"][own], w["cust_at"][own])
    order_id, cust = w["spare"]
    other = _escalate(w, order_id, cust)
    hq = w["ids"][_staff(w["cfg"], "hq_owner")[0].email]
    assert _reassign(w, headers, mine, hq).status_code == 403  # sees it, may not hand it on
    assert _reassign(w, headers, other, hq).status_code == 404  # another outlet: absent
    assert w["api"].get(f"/cases/{other}", headers=headers).status_code == 404
    assert {uuid.UUID(r["case_id"]) for r in _mine(w, _queue(w, headers))} == {mine}


def test_franchisee_reassigns_within_their_outlets(world):
    w = world
    franchisees = _staff(w["cfg"], "franchisee_owner")
    if not franchisees:
        pytest.skip("this tenant has no franchisee_owner")
    fr = franchisees[0]
    headers = login(w["api"], w["cfg"].slug, fr.email)
    own = next(i for s, i in w["locs"].items() if s in fr.locations and i in w["order_at"])
    mine = _escalate(w, w["order_at"][own], w["cust_at"][own])
    order_id, cust = w["spare"]
    other = _escalate(w, order_id, cust)
    target = w["ids"][fr.email]
    assert _reassign(w, headers, mine, target).status_code == 200
    assert _owner(w, mine) == target
    assert _reassign(w, headers, other, target).status_code == 404


def test_other_tenant_staff_get_404(world, seeded_history):
    w = world
    loc_id = next(i for i in w["locs"].values() if i in w["order_at"])
    cid = _escalate(w, w["order_at"][loc_id], w["cust_at"][loc_id])
    others = [c for c in seeded_history.values() if c.slug != w["cfg"].slug]
    assert others, "needs two tenants"
    foreign = next(u for u in others[0].users if u.role == "hq_owner")
    headers = login(w["api"], others[0].slug, foreign.email)
    me = w["ids"][_staff(w["cfg"], "hq_owner")[0].email]
    assert _reassign(w, headers, cid, me).status_code == 404
    assert _mine(w, _queue(w, headers)) == []
