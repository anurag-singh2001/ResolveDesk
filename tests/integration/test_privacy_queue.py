# ruff: noqa: F811, F401
"""S8.5e: the owner's privacy request queue, dry run and bound, expiring approval.

Runs for every tenant and names none.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.api.deps import get_clock
from app.core.db import tenant_session
from app.core.models import AuditEvent, Customer, DataRequest, Ticket
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine import privacy_queue
from app.engine.sweeper import sweep_tenant
from tests.helpers import login
from tests.integration import test_retention as ret
from tests.integration.test_data_rights import (
    SimpleId,
    _erasable,
    _request,
    people,
    slug,
    staff,
)

made = ret.made
tid = ret.tid


def _look(api, hq, rid):
    r = api.get(f"/data-requests/{rid}/dry-run", headers=hq)
    assert r.status_code == 200, r.text
    return r.json()


def _approve_with(api, hq, rid, look):
    return api.post(
        f"/data-requests/{rid}/approve",
        json={"payload_hash": look["payload_hash"], "approval_token": look["approval_token"]},
        headers=hq,
    )


def _name(app_engine, tid, cid):
    with tenant_session(tid, app_engine) as s:
        return s.get(Customer, cid).name


def _row(api, hq, rid):
    items = api.get("/data-requests/queue", headers=hq).json()["items"]
    return next(i for i in items if i["id"] == rid)


def test_queue_lists_open_requests_masked_with_dates(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    body = api.get("/data-requests/queue", headers=hq).json()
    row = _row(api, hq, req["id"])
    assert row["stage"] == "received" and row["overdue"] is False
    assert 0 <= row["days_left"] <= body["target_days"]
    assert row["target_at"] and row["received_at"]
    with tenant_session(tid, app_engine) as s:
        ref = s.get(Customer, cid).external_ref
    assert row["customer_ref"] != ref and "*" in row["customer_ref"]
    assert "Real Person" not in str(body)


def test_scope_non_hq_is_403_and_other_tenant_is_404(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    req = _request(api, auth)
    for headers in (auth, staff(api, tenant, slug, "location_manager")):
        assert api.get("/data-requests/queue", headers=headers).status_code == 403
        assert api.get(f"/data-requests/{req['id']}/dry-run", headers=headers).status_code == 403
        url = f"/data-requests/{req['id']}/approve"
        assert api.post(url, json={}, headers=headers).status_code == 403
    other_cfg = load_tenant(next(p for p in tenant_dirs() if p.name != tenant.name))
    email = next(u.email for u in other_cfg.users if u.role == "hq_owner")
    other_hq = login(api, other_cfg.slug, email)
    assert req["id"] not in str(api.get("/data-requests/queue", headers=other_hq).json())
    assert api.get(f"/data-requests/{req['id']}/dry-run", headers=other_hq).status_code == 404
    url = f"/data-requests/{req['id']}/approve"
    assert api.post(url, json={}, headers=other_hq).status_code == 404
    assert _name(app_engine, tid, cid) == "Real Person"


def test_dry_run_is_counts_only_and_matches_the_erasure(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    look = _look(api, hq, req["id"])
    assert "Real Person" not in str(look)
    assert look["remove"]["name"] == 1
    assert look["keep"]["orders"] >= 1 and look["keep"]["cases"] >= 1
    assert all(isinstance(v, int) for v in look["remove"].values())
    assert all(isinstance(v, int) for v in look["keep"].values())
    assert look["deferred"] is None
    assert _approve_with(api, hq, req["id"], look).status_code == 200
    with tenant_session(tid, app_engine) as s:
        row = s.get(DataRequest, uuid.UUID(req["id"]))
        after = privacy_queue.dry_run(s, tid, row, datetime.now(UTC))
    assert after["remove"]["name"] == 0 and after["remove"]["contact_fields"] == 0
    assert after["remove"]["messages"] == 0
    assert after["keep"] == look["keep"]  # what is kept is still there


def test_approval_needs_the_dry_run_hash_and_a_genuine_token(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    look = _look(api, hq, req["id"])
    url = f"/data-requests/{req['id']}/approve"
    assert api.post(url, headers=hq).status_code == 409
    bad_hash = {"payload_hash": "0" * 64, "approval_token": look["approval_token"]}
    assert api.post(url, json=bad_hash, headers=hq).status_code == 409
    forged = {"payload_hash": look["payload_hash"], "approval_token": "1.deadbeef"}
    assert api.post(url, json=forged, headers=hq).status_code == 409
    assert _name(app_engine, tid, cid) == "Real Person"
    assert _approve_with(api, hq, req["id"], look).status_code == 200


def test_a_token_does_not_work_on_another_request(api, app_engine, tid, made, people, tenant, slug):
    cid, auth = people()
    cid2, auth2 = people("Second Person")
    _erasable(app_engine, tid, made, cid)
    _erasable(app_engine, tid, made, cid2)
    hq = staff(api, tenant, slug, "hq_owner")
    first, second = _request(api, auth), _request(api, auth2)
    look = _look(api, hq, first["id"])
    assert _approve_with(api, hq, second["id"], look).status_code == 409
    assert _name(app_engine, tid, cid2) == "Second Person"


def test_stale_when_the_customers_data_changes_after_the_dry_run(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    look = _look(api, hq, req["id"])
    # The customer changes something after the owner looked: a consent is now on.
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth)
    r = _approve_with(api, hq, req["id"], look)
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    assert _name(app_engine, tid, cid) == "Real Person"
    fresh = _look(api, hq, req["id"])  # reviewing again gives a new hash that works
    assert fresh["payload_hash"] != look["payload_hash"]
    assert _approve_with(api, hq, req["id"], fresh).status_code == 200


def test_expired_approval_is_refused(api, app_engine, tid, made, people, tenant, slug):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    look = _look(api, hq, req["id"])
    later = datetime.now(UTC) + privacy_queue.APPROVAL_TTL + timedelta(minutes=1)
    api.app.dependency_overrides[get_clock] = lambda: later
    try:
        r = _approve_with(api, hq, req["id"], look)
    finally:
        api.app.dependency_overrides.pop(get_clock, None)
    assert r.status_code == 409 and "expired" in r.json()["detail"]
    assert _name(app_engine, tid, cid) == "Real Person"


def test_withdrawn_while_reviewing_erases_nothing_and_leaves_the_queue(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    look = _look(api, hq, req["id"])
    assert api.post("/me/erasure-request/cancel", headers=auth).status_code == 200
    r = _approve_with(api, hq, req["id"], look)
    assert r.status_code == 409 and "withdrew" in r.json()["detail"]
    assert _name(app_engine, tid, cid) == "Real Person"
    assert req["id"] not in str(api.get("/data-requests/queue", headers=hq).json())
    assert api.get(f"/data-requests/{req['id']}/dry-run", headers=hq).status_code == 409


def test_completed_request_leaves_the_queue(api, app_engine, tid, made, people, tenant, slug):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    assert _approve_with(api, hq, req["id"], _look(api, hq, req["id"])).status_code == 200
    assert req["id"] not in str(api.get("/data-requests/queue", headers=hq).json())


def test_deferral_is_shown_and_approving_keeps_it_deferred(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    with tenant_session(tid, app_engine) as s:  # a recent order: inside the one-year floor
        ret._order(s, tid, made, SimpleId(cid), 5)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    assert req["status"] == "deferred"
    row = _row(api, hq, req["id"])
    assert row["stage"] == "deferred" and row["reason_code"] == "retention_floor" and row["reason"]
    look = _look(api, hq, req["id"])
    assert look["deferred"]["code"] == "retention_floor" and look["deferred"]["reason"]
    r = _approve_with(api, hq, req["id"], look)
    assert r.status_code == 200 and r.json()["status"] == "deferred"
    assert _name(app_engine, tid, cid) == "Real Person"


def test_sweeper_flags_near_and_overdue_once_without_personal_content(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    rid = uuid.UUID(req["id"])
    target = api.get("/data-requests/queue", headers=hq).json()["target_days"]

    def events():
        with tenant_session(tid, app_engine) as s:
            return sorted(
                s.scalars(
                    select(AuditEvent.event).where(
                        AuditEvent.entity_id == rid,
                        AuditEvent.event.in_(
                            (privacy_queue.DUE_SOON_EVENT, privacy_queue.OVERDUE_EVENT)
                        ),
                    )
                ).all()
            )

    base = datetime.now(UTC)
    assert privacy_queue.flag_due(app_engine, tid, base) == []
    near = base + timedelta(days=target * 0.8)
    assert str(rid) in privacy_queue.flag_due(app_engine, tid, near)
    assert privacy_queue.flag_due(app_engine, tid, near) == []  # once per transition
    assert events() == [privacy_queue.DUE_SOON_EVENT]
    late = base + timedelta(days=target + 1)
    assert str(rid) in sweep_tenant(app_engine, tid, now=late).erasure_requests_flagged
    assert events() == [privacy_queue.DUE_SOON_EVENT, privacy_queue.OVERDUE_EVENT]
    api.app.dependency_overrides[get_clock] = lambda: late
    try:
        row = _row(api, hq, req["id"])
    finally:
        api.app.dependency_overrides.pop(get_clock, None)
    assert row["overdue"] is True and row["days_left"] < 0
    with tenant_session(tid, app_engine) as s:
        payloads = s.scalars(select(AuditEvent.payload).where(AuditEvent.entity_id == rid)).all()
    assert "Real Person" not in str(payloads)


def test_withdrawn_request_is_not_flagged(api, app_engine, tid, made, people, tenant, slug):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    req = _request(api, auth)
    api.post("/me/erasure-request/cancel", headers=auth)
    far = datetime.now(UTC) + timedelta(days=400)
    assert req["id"] not in privacy_queue.flag_due(app_engine, tid, far)


def test_review_and_approval_are_audited_without_personal_content(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    assert _approve_with(api, hq, req["id"], _look(api, hq, req["id"])).status_code == 200
    with tenant_session(tid, app_engine) as s:
        rows = s.execute(
            select(AuditEvent.event, AuditEvent.payload).where(
                AuditEvent.entity_id == uuid.UUID(req["id"])
            )
        ).all()
    names = [e for e, _ in rows]
    for event in (
        "privacy.erasure_reviewed",
        "privacy.erasure_approved",
        "privacy.erasure_completed",
    ):
        assert event in names
    assert "Real Person" not in str(rows)
