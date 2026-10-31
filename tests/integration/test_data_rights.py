"""Customer data rights (S5.2): consent history, access export, erasure request.

Runs for every tenant and names none. Each test builds the customers it needs (with a login
token minted for them) and removes them afterwards; audit rows stay (append-only). Assertions
are on those rows, never on global counts.
"""

import threading
import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.core.auth import issue_token
from app.core.db import tenant_session
from app.core.models import (
    AuditEvent,
    Consent,
    ConsentEvent,
    Customer,
    DataRequest,
    Membership,
    RefundOperation,
    Transaction,
    User,
)
from app.core.tenancy import load_context, tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine import data_rights as privacy
from app.engine.cases import CaseNotFound, open_case
from app.engine.data_rights import erasure_block
from app.modules.growth import campaigns as camp
from app.modules.growth.campaigns import ProposalError
from app.modules.growth.executor import execute_campaign
from tests.helpers import login
from tests.integration import test_growth as growth_tests
from tests.integration import test_retention as ret
from tests.integration.test_growth import (
    approvers,
    decide_as,
    make_signal,
    outbox,
    propose_for,
    third_party,
)
from tests.integration.test_retention import (
    KEPT,
    NOW,
    PROTECTED,
    _bodies,
    _case,
    _customer_row,
    _money,
    _order,
    _snapshot,
)

# Fixtures reused from the retention and growth tests (pytest finds them by name here).
made = ret.made
tid = ret.tid
gt = growth_tests.gt


@pytest.fixture
def slug(tenant):
    return load_tenant(tenant).slug


@pytest.fixture
def people(app_engine, maint_engine, tid, made):  # noqa: F811
    """Make customers who can log in; removes their users afterwards (before `made` cleans)."""
    users: list[uuid.UUID] = []
    customers: list[uuid.UUID] = []

    def make(name="Real Person"):
        with tenant_session(tid, app_engine) as s:
            user = User(
                tenant_id=tid,
                email=f"priv-{uuid.uuid4().hex[:10]}@example.test",
                display_name=name,
            )
            s.add(user)
            s.flush()
            s.add(Membership(tenant_id=tid, user_id=user.id, role="customer"))
            c = Customer(
                tenant_id=tid,
                external_ref=f"priv-{uuid.uuid4().hex[:12]}",
                name=name,
                phone=KEPT[1],
                email=KEPT[2],
                user_id=user.id,
            )
            s.add(c)
            s.flush()
            users.append(user.id)
            customers.append(c.id)
            made["tid"].append(tid)
            made["customers"].append(c.id)
            return c.id, {"Authorization": f"Bearer {issue_token(tid, user.id)}"}

    yield make
    with tenant_session(tid, maint_engine) as s:
        # Consent history is RESTRICTed against customer deletion (owner-level cleanup only).
        s.execute(delete(ConsentEvent).where(ConsentEvent.customer_id.in_(customers)))
        s.execute(delete(Membership).where(Membership.user_id.in_(users)))
        s.execute(update(Customer).where(Customer.user_id.in_(users)).values(user_id=None))
        s.execute(delete(User).where(User.id.in_(users)))


def staff(api, tenant, slug, role):
    cfg = load_tenant(tenant)
    email = next(u.email for u in cfg.users if u.role == role)
    return login(api, slug, email)


# -- consent -----------------------------------------------------------------------------


def test_consent_grant_and_withdraw_are_one_call_and_kept_in_history(api, people):
    cid, auth = people()
    first = api.get("/me/consents", headers=auth).json()
    assert [c["granted"] for c in first["consents"]] == [False]  # no row means no consent
    for granted in (True, False, True, False):
        r = api.post("/me/consents/marketing", json={"granted": granted}, headers=auth)
        assert r.status_code == 200
        assert r.json()["consents"][0]["granted"] is granted
    out = api.get("/me/consents", headers=auth).json()
    assert out["consents"][0]["granted"] is False  # the current state is the last decision
    assert [e["granted"] for e in out["history"]] == [True, False, True, False]
    assert {e["notice_version"] for e in out["history"]} == {privacy.NOTICE_VERSION}
    # Repeating the current state adds no history row.
    api.post("/me/consents/marketing", json={"granted": False}, headers=auth)
    assert len(api.get("/me/consents", headers=auth).json()["history"]) == 4
    # A first-ever withdrawal is recorded too.
    cid2, auth2 = people()
    api.post("/me/consents/marketing", json={"granted": False}, headers=auth2)
    assert [e["granted"] for e in api.get("/me/consents", headers=auth2).json()["history"]] == [
        False
    ]
    assert api.post("/me/consents/service", json={"granted": True}, headers=auth).status_code == 404


def test_app_role_cannot_edit_or_delete_consent_history(api, app_engine, tid, people):
    cid, auth = people()
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth)
    for stmt in (
        update(ConsentEvent).where(ConsentEvent.customer_id == cid).values(granted=False),
        delete(ConsentEvent).where(ConsentEvent.customer_id == cid),
    ):
        with pytest.raises(DBAPIError), tenant_session(tid, app_engine) as s:
            s.execute(stmt)


def test_growth_send_skips_a_customer_who_withdrew_after_approval(app_engine, maint_engine, gt):  # noqa: F811
    cfg, tid_, as_of = gt
    signal_id = make_signal(app_engine, tid_, as_of)
    from app.core.models import Signal

    with tenant_session(tid_, app_engine) as s:
        loc = s.get(Signal, signal_id).location_id
    hq, other = approvers(app_engine, cfg, tid_, loc)
    try:
        cid, _ = propose_for(
            app_engine, tid_, signal_id, third_party(app_engine, cfg, tid_, loc, hq, other)
        )
    except ProposalError:
        pytest.skip("history too small for an audience at this scale")
    decide_as(app_engine, tid_, hq, cid)
    decide_as(app_engine, tid_, other, cid)
    with tenant_session(tid_, app_engine) as s:
        c = s.get(camp.Campaign, cid)
        treatment = [m.customer_id for m in camp.members_of(s, c) if m.arm == "treatment"]
        phones = {i: p for i, p in s.execute(select(Customer.id, Customer.phone))}
    leaver = treatment[0]
    try:
        with tenant_session(tid_, app_engine) as s:  # the same code path as the endpoint
            assert privacy.set_consent(s, tid_, leaver, "marketing", "whatsapp", False)
        assert execute_campaign(app_engine, tid_, cid).outcome == "sent"
        sent_to = [r.to for r in outbox(tid_)]
        assert phones[leaver] not in sent_to
        assert sorted(sent_to) == sorted(phones[i] for i in treatment[1:])
    finally:  # put the shared seed back
        with tenant_session(tid_, maint_engine) as s:
            s.execute(delete(ConsentEvent).where(ConsentEvent.customer_id == leaver))
            s.execute(
                update(Consent)
                .where(Consent.customer_id == leaver, Consent.purpose == "marketing")
                .values(granted=True)
            )


# -- access ------------------------------------------------------------------------------


def test_export_has_only_the_callers_data(api, app_engine, maint_engine, tid, made, people):  # noqa: F811
    a, auth_a = people("Alice Anand")
    b, auth_b = people("Bruno Bose")
    with tenant_session(tid, app_engine) as s:
        order_a = _order(s, tid, made, SimpleId(a), 10)
        order_b = _order(s, tid, made, SimpleId(b), 10)
        case_a = _case(s, tid, made, SimpleId(a), status="closed", age_days=10)
        _case(s, tid, made, SimpleId(b), status="closed", age_days=10)
        ref_a = s.get(Transaction, order_a.id).external_ref
        ref_b = s.get(Transaction, order_b.id).external_ref
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth_a)
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth_b)

    r = api.get("/me/data-export", headers=auth_a)
    assert r.status_code == 200
    body = r.json()
    text = r.text
    assert body["profile"]["name"] == "Alice Anand"
    assert [o["order_ref"] for o in body["orders"]] == [ref_a]
    assert ref_b not in text and "Bruno" not in text
    assert [c["id"] for c in body["cases"]] == [str(case_a.id)]
    assert body["consents"]["history"][0]["granted"] is True
    assert len(body["consents"]["history"]) == 1
    assert all(p["name"] and p["role"] for p in body["processors"]) and any(
        "Gemini" in p["name"] for p in body["processors"]
    )
    assert all(isinstance(o["total_paise"], int) for o in body["orders"])


def SimpleId(i):  # a customer reference with just an id, as the retention helpers expect
    from types import SimpleNamespace

    return SimpleNamespace(id=i)


def test_export_never_shows_another_tenants_customer(api, maint_engine, people, tenant):
    _, auth = people("Alice Anand")
    other = next(p for p in tenant_dirs() if p.name != tenant.name)
    other_tid = tenant_id_for(load_tenant(other).slug)
    ref = f"xt-{uuid.uuid4().hex[:10]}"
    with tenant_session(other_tid, maint_engine) as s:
        c = Customer(tenant_id=other_tid, external_ref=ref, name="Zed Zoo", phone="9000000001")
        s.add(c)
        s.flush()
        cid = c.id
    try:
        text = api.get("/me/data-export", headers=auth).text
        assert ref not in text and "Zed Zoo" not in text and "9000000001" not in text
    finally:
        with tenant_session(other_tid, maint_engine) as s:
            s.execute(delete(Customer).where(Customer.id == cid))


# -- erasure -----------------------------------------------------------------------------


def _request(api, auth):
    r = api.post("/me/erasure-request", headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _approve(api, hq, request_id):
    look = api.get(f"/data-requests/{request_id}/dry-run", headers=hq)  # the approval needs it
    # A completed request has no dry run; approving it again is the idempotent no-op.
    assert look.status_code in (200, 409), look.text
    approval = (
        {k: look.json()[k] for k in ("payload_hash", "approval_token")} if look.is_success else {}
    )
    r = api.post(f"/data-requests/{request_id}/approve", json=approval, headers=hq)
    assert r.status_code == 200, r.text
    return r.json()


def test_erasure_is_deferred_while_a_refund_is_in_flight(
    api,
    app_engine,
    maint_engine,
    tid,
    made,
    people,
    tenant,
    slug,  # noqa: F811
):
    cid, auth = people()
    hq = staff(api, tenant, slug, "hq_owner")
    with tenant_session(tid, app_engine) as s:
        order = _order(s, tid, made, SimpleId(cid), 400)
        case = _case(s, tid, made, SimpleId(cid), status="closed", age_days=400)
        _money(s, tid, case, approved=True, refund="submitted", txn=order)
    req = _request(api, auth)
    assert req["status"] == "deferred"
    assert req["reason"] == privacy.REASONS["in_flight"]
    assert api.get("/me/erasure-request", headers=auth).json()["id"] == req["id"]
    assert _request(api, auth)["id"] == req["id"]  # one active request, not a pile
    assert _approve(api, hq, req["id"])["status"] == "deferred"  # staff cannot force it
    assert _customer_row(app_engine, tid, cid)[1:] == KEPT[1:]  # nothing was erased
    # Once the refund has settled, the same request goes through.
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            update(RefundOperation)
            .where(RefundOperation.transaction_id == order.id)
            .values(status="succeeded")
        )
    done = _approve(api, hq, req["id"])
    assert done["status"] == "completed" and done["reason"] is None


@pytest.mark.parametrize(
    ("status", "ticket", "age", "hold", "code"),
    [
        ("closed", "closed", 100, False, "retention_floor"),
        ("open", "open", 400, False, "open_case"),
        ("escalated", "escalated", 400, False, "open_case"),
        ("closed", "closed", 400, True, "legal_hold"),
    ],
)
def test_erasure_is_deferred_with_a_reason(
    api,
    app_engine,
    tid,
    made,
    people,
    status,
    ticket,
    age,
    hold,
    code,  # noqa: F811
):
    cid, auth = people()
    with tenant_session(tid, app_engine) as s:
        _case(s, tid, made, SimpleId(cid), status=status, age_days=age, hold=hold, ticket=ticket)
    req = _request(api, auth)
    assert req["status"] == "deferred"
    assert req["reason"] and req["reason"].split()[0]  # template text, never empty
    with tenant_session(tid, app_engine) as s:
        row = s.get(DataRequest, uuid.UUID(req["id"]))
        assert row.reason_code == code
        if code == "retention_floor":
            assert row.deferred_until is not None and row.deferred_until > NOW
            assert row.deferred_until.date().isoformat() in req["reason"]
    assert _customer_row(app_engine, tid, cid)[1:] == KEPT[1:]


def test_approved_erasure_redacts_and_leaves_money_and_audit_alone(
    api,
    app_engine,
    maint_engine,
    tid,
    made,
    people,
    tenant,
    slug,  # noqa: F811
):
    cid, auth = people()
    hq = staff(api, tenant, slug, "hq_owner")
    with tenant_session(tid, app_engine) as s:
        order = _order(s, tid, made, SimpleId(cid), 400)
        case = _case(s, tid, made, SimpleId(cid), status="closed", age_days=400)
        _money(s, tid, case, approved=True, execution="succeeded", verified=True, txn=order)
        user_id = s.get(Customer, cid).user_id
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth)
    assert _bodies(app_engine, tid, case.id) != []

    req = _request(api, auth)
    assert req["status"] == "pending_approval"  # waits for a person
    assert _customer_row(app_engine, tid, cid)[1:] == KEPT[1:]
    listed = api.get("/data-requests", headers=hq).json()
    assert req["id"] in [r["id"] for r in listed]
    before = _snapshot(app_engine, tid)
    assert _approve(api, hq, req["id"])["status"] == "completed"
    after = _snapshot(app_engine, tid)

    assert all(row in after["audit"] for row in before["audit"])  # no audit row changed or went
    assert len(after["audit"]) > len(before["audit"])
    for table in [m.__tablename__ for m in PROTECTED] + ["refund_operations"]:
        assert after[table] == before[table]  # money, proposals, approvals: untouched
    assert set(_bodies(app_engine, tid, case.id)) == {"[redacted after retention period]"}
    assert _customer_row(app_engine, tid, cid) == ("[redacted]", None, None)
    with tenant_session(tid, app_engine) as s:
        user = s.get(User, user_id)
        assert user.password_hash is None and user.email.endswith("@erased.invalid")
        assert s.scalar(select(Consent.granted).where(Consent.customer_id == cid)) is False
        sources = s.scalars(
            select(ConsentEvent.source)
            .where(ConsentEvent.customer_id == cid)
            .order_by(ConsentEvent.created_at, ConsentEvent.id)
        ).all()
        assert sources == ["customer", "erasure"]
        events = s.scalars(
            select(AuditEvent.event).where(AuditEvent.entity_id == uuid.UUID(req["id"]))
        )
        assert "privacy.erasure_completed" in events.all()
    assert _approve(api, hq, req["id"])["status"] == "completed"  # idempotent
    assert _snapshot(app_engine, tid) == after  # a second approval changes nothing


def test_erasure_block_clears_when_nothing_is_pending(app_engine, tid, made):  # noqa: F811
    with tenant_session(tid, app_engine) as s:
        c = Customer(tenant_id=tid, external_ref=f"priv-{uuid.uuid4().hex[:10]}", name="N")
        s.add(c)
        s.flush()
        made["tid"].append(tid)
        made["customers"].append(c.id)
        assert erasure_block(s, tid, c.id, datetime.now(UTC)) is None  # nothing on record


# -- who may call what -------------------------------------------------------------------


@pytest.mark.parametrize("role", ["hq_owner", "location_manager"])
def test_staff_cannot_use_my_endpoints(api, tenant, slug, role):
    cfg = load_tenant(tenant)
    if not any(u.role == role for u in cfg.users):
        pytest.skip("tenant has no such role")
    auth = staff(api, tenant, slug, role)
    assert api.get("/me/consents", headers=auth).status_code == 403
    assert (
        api.post("/me/consents/marketing", json={"granted": True}, headers=auth).status_code == 403
    )
    assert api.get("/me/data-export", headers=auth).status_code == 403
    assert api.post("/me/erasure-request", headers=auth).status_code == 403
    assert api.get("/me/erasure-request", headers=auth).status_code == 403


def test_customers_cannot_work_requests_and_anonymous_is_refused(api, people):
    cid, auth = people()
    assert api.get("/data-requests", headers=auth).status_code == 403
    assert api.post(f"/data-requests/{uuid.uuid4()}/approve", headers=auth).status_code == 403
    assert api.get("/me/consents").status_code == 401
    assert api.get("/me/data-export").status_code == 401


def _erasable(app_engine, tid, made, cid):
    with tenant_session(tid, app_engine) as s:
        order = _order(s, tid, made, SimpleId(cid), 400)
        _case(s, tid, made, SimpleId(cid), status="closed", age_days=400)
    return order


def test_tokens_issued_before_erasure_stop_working(
    api,
    app_engine,
    tid,
    made,
    people,
    tenant,
    slug,  # noqa: F811
):
    cid, auth = people()
    order = _erasable(app_engine, tid, made, cid)
    assert api.get("/me/data-export", headers=auth).status_code == 200
    req = _request(api, auth)
    hq = staff(api, tenant, slug, "hq_owner")
    assert _approve(api, hq, req["id"])["status"] == "completed"
    assert api.get("/me/data-export", headers=auth).status_code == 401
    assert (
        api.post("/me/consents/marketing", json={"granted": True}, headers=auth).status_code == 401
    )
    body = {"transaction_id": str(order.id), "category": None, "message": "x"}
    assert api.post("/cases", json=body, headers=auth).status_code == 401


def test_a_second_request_returns_the_first_even_when_simultaneous(
    app_engine,
    tid,
    made,
    people,  # noqa: F811
):
    cid, _ = people()
    ids = []

    def go():
        with tenant_session(tid, app_engine) as s:
            ids.append(privacy.request_erasure(s, tid, cid, datetime.now(UTC)).id)

    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ids) == 3 and len(set(ids)) == 1
    with tenant_session(tid, app_engine) as s:
        rows = s.scalars(select(DataRequest).where(DataRequest.customer_id == cid)).all()
    assert len(rows) == 1


def test_case_writes_serialize_with_erasure(app_engine, tid, made, people):  # noqa: F811
    """A report that starts while an erasure is in progress waits for it, then finds the
    account erased; it never lands a case on redacted data."""
    cid, auth = people()
    order = _erasable(app_engine, tid, made, cid)
    with tenant_session(tid, app_engine) as s:
        user_id = s.get(Customer, cid).user_id
        ctx = load_context(s, tid, user_id)
        req_id = privacy.request_erasure(s, tid, cid, datetime.now(UTC)).id
    result = {}

    def report():
        try:
            with tenant_session(tid, app_engine) as s:
                open_case(
                    s,
                    ctx,
                    transaction_id=order.id,
                    category=None,
                    message="late",
                    now=datetime.now(UTC),
                )
            result["out"] = "opened"
        except CaseNotFound:
            result["out"] = "refused"

    with tenant_session(tid, app_engine) as s:
        done = privacy.run_erasure(s, tid, req_id, None, datetime.now(UTC), guard=None)
        assert done.status == "completed"
        t = threading.Thread(target=report)
        t.start()
        time.sleep(1.5)
        assert "out" not in result  # waiting on the customer lock; erasure not yet committed
    t.join(timeout=30)
    assert result["out"] == "refused"
    with tenant_session(tid, app_engine) as s:
        assert load_context(s, tid, user_id) is None


def test_consent_audit_names_the_customer_and_first_decisions_race_safely(
    api,
    app_engine,
    tid,
    people,  # noqa: F811
):
    cid, auth = people()
    me = api.get("/me", headers=auth).json()["user_id"]
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth)
    with tenant_session(tid, app_engine) as s:
        actors = s.scalars(
            select(AuditEvent.actor_id).where(
                AuditEvent.entity_id == cid, AuditEvent.event == "consent.granted"
            )
        ).all()
    assert actors == [me]
    cid2, _ = people()

    def go(granted):
        with tenant_session(tid, app_engine) as s:
            privacy.set_consent(s, tid, cid2, "marketing", "whatsapp", granted)

    threads = [threading.Thread(target=go, args=(g,)) for g in (True, False, True)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with tenant_session(tid, app_engine) as s:
        rows = s.scalars(select(Consent).where(Consent.customer_id == cid2)).all()
        events = s.scalars(select(ConsentEvent).where(ConsentEvent.customer_id == cid2)).all()
    assert len(rows) == 1  # one row per (customer, channel, purpose), no matter the race
    assert 1 <= len(events) <= 3


def test_unknown_request_is_404_for_the_owner(api, tenant, slug):
    hq = staff(api, tenant, slug, "hq_owner")
    assert api.post(f"/data-requests/{uuid.uuid4()}/approve", headers=hq).status_code == 404
