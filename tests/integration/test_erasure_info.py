# ruff: noqa: F811, F401
"""S8.5d: erasure explained and tracked.

Runs for every tenant and names none. The wording is tested against what the erasure and
retention code really does: every "we remove" line is checked after a real erasure, every
"we keep" line is checked to still exist, every "we may wait" reason is a real block code.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES, TEMPLATES, t
from app.core.models import (
    AuditEvent,
    Case,
    ConsentEvent,
    Customer,
    DataRequest,
    Transaction,
    User,
)
from app.core.settings_resolver import effective_settings
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine import data_held, erasure_info
from app.engine import data_rights as privacy
from tests.integration import test_retention as ret
from tests.integration.test_data_rights import (
    SimpleId,
    _approve,
    _erasable,
    _request,
    people,
    slug,
    staff,
)
from tests.integration.test_retention import _bodies, _case, _money, _order, _snapshot

made = ret.made
tid = ret.tid


def _info(api, auth):
    r = api.get("/me/erasure-info", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


# -- the explanation ---------------------------------------------------------------------


def test_info_has_three_lists_with_a_reason_per_kept_item(api, people):
    _, auth = people()
    body = _info(api, auth)
    assert [body["headings"][k] for k in ("remove", "keep", "wait")] == [
        "We will remove",
        "We will keep",
        "We may wait",
    ]
    assert len(body["remove"]) == len(erasure_info.REMOVE) and all(body["remove"])
    assert [k["key"] for k in body["keep"]] == list(erasure_info.KEEP)
    assert all(k["label"] and k["reason"] for k in body["keep"])
    assert body["wait"] and all(body["wait"])
    assert body["buttons"]["back"] != body["buttons"]["confirm"]
    assert body["confirm"]["title"] and body["confirm"]["body"]


def test_wait_list_covers_every_real_block_code():
    codes = set(privacy.REASONS)
    assert codes == set(erasure_info.WAIT_CODES) | {"retention_floor"}


def test_info_numbers_come_from_settings_and_code(api, app_engine, tid, people):
    _, auth = people()
    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    body = _info(api, auth)
    assert body["target_days"] == data_held.target_days(settings)
    assert body["legal_ceiling_days"] == data_held.LEGAL_CEILING_DAYS == 90
    records = next(k for k in body["keep"] if k["key"] == "records")
    assert str(settings["payment_retention_years"]) in records["reason"]
    assert records["provisional"] is True and body["provisional_label"]
    assert body["contact"]["email"] == settings["privacy_contact_email"]
    for bad in ("x", None, 0, 91, True, -1):
        assert data_held.target_days({"grievance_target_days": bad}) == 30
    assert data_held.target_days({"grievance_target_days": 7}) == 7


def test_erasure_does_what_the_lists_say(api, app_engine, tid, made, people, tenant, slug):
    """Every removed item is gone after a real erasure; every kept item is still there."""
    cid, auth = people("Real Person")
    hq = staff(api, tenant, slug, "hq_owner")
    with tenant_session(tid, app_engine) as s:
        order = _order(s, tid, made, SimpleId(cid), 400)
        case = _case(s, tid, made, SimpleId(cid), status="closed", age_days=400)
        _money(s, tid, case, approved=True, execution="succeeded", verified=True, txn=order)
        customer = s.get(Customer, cid)
        customer.attributes = {"note": "likes it spicy"}
        ref, user_id = customer.external_ref, customer.user_id
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth)
    assert _bodies(app_engine, tid, case.id) != []
    before = _snapshot(app_engine, tid)

    req = _request(api, auth)
    assert _approve(api, hq, req["id"])["status"] == "completed"

    with tenant_session(tid, app_engine) as s:
        c = s.get(Customer, cid)
        # remove: name, contact, message text, profile details, login, offers
        assert c.name == "[redacted]" and c.phone is None and c.email is None
        assert c.attributes == {}
        assert set(_bodies(app_engine, tid, case.id)) == {"[redacted after retention period]"}
        user = s.get(User, user_id)
        assert user.password_hash is None and user.erased_at is not None
        assert (
            s.scalar(
                select(ConsentEvent.granted)
                .where(ConsentEvent.customer_id == cid)
                .order_by(ConsentEvent.created_at.desc())
                .limit(1)
            )
            is False
        )
        # keep: orders and payments, case records, audit log, consent history, reference
        assert s.get(Transaction, order.id).total_paise is not None  # amounts stay (snapshot below)
        kept_case = s.get(Case, case.id)
        assert kept_case.status == "closed" and kept_case.customer_id == cid
        assert c.external_ref == ref
        assert (
            s.scalar(select(ConsentEvent.id).where(ConsentEvent.customer_id == cid).limit(1))
            is not None
        )
    after = _snapshot(app_engine, tid)
    for table in ("transactions", "payments", "action_proposals", "approvals", "executions"):
        assert after[table] == before[table]
    assert all(row in after["audit"] for row in before["audit"])
    assert len(erasure_info.REMOVE) == 6 and len(erasure_info.KEEP) == 5  # lists reviewed


# -- tracking a request ------------------------------------------------------------------


def test_request_shows_stage_dates_and_contact(api, app_engine, tid, made, people):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    assert api.get("/me/erasure-request", headers=auth).json() is None
    req = _request(api, auth)
    assert req["stage"] == "received" and req["stage_label"] == "Received"
    received = datetime.fromisoformat(req["received_at"])
    days = data_held.target_days(settings)
    assert datetime.fromisoformat(req["expected_by"]) == received + timedelta(days=days)
    assert datetime.fromisoformat(req["legal_ceiling_by"]) == received + timedelta(days=90)
    assert req["can_withdraw"] is True and req["reason_code"] is None
    assert "Nothing has been erased" in req["stage_text"]
    assert req["contact"]["email"] == settings["privacy_contact_email"]
    again = api.get("/me/erasure-request", headers=auth).json()
    assert again["id"] == req["id"] and again["stage"] == "received"


def test_a_repeat_request_returns_the_same_one(api, app_engine, tid, made, people):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    first = _request(api, auth)
    second = _request(api, auth)
    assert second["id"] == first["id"]
    with tenant_session(tid, app_engine) as s:
        n = s.scalars(select(DataRequest.id).where(DataRequest.customer_id == cid)).all()
        assert len(n) == 1


def test_open_case_defers_with_code_and_reason_never_done(api, app_engine, tid, made, people):
    cid, auth = people()
    with tenant_session(tid, app_engine) as s:
        _case(s, tid, made, SimpleId(cid), status="open", age_days=400, ticket="open")
    req = _request(api, auth)
    assert req["stage"] == "deferred" and req["stage_label"] == "Could not complete yet"
    assert req["reason_code"] == "open_case"
    assert req["reason"] in req["stage_text"] and "Nothing has been erased" in req["stage_text"]
    assert req["can_withdraw"] is True and req["expected_by"]
    assert "done" not in req["stage_label"].lower()
    assert req["completed_at"] is None


def test_done_only_after_the_executor_succeeded(api, app_engine, tid, made, people, tenant, slug):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    assert req["stage"] != "done"
    # A case opens before the owner approves: the executor re-checks, defers, and says why.
    with tenant_session(tid, app_engine) as s:
        _case(s, tid, made, SimpleId(cid), status="open", age_days=1, ticket="open")
    deferred = _approve(api, hq, req["id"])
    assert deferred["status"] == "deferred"
    mine = api.get("/me/erasure-request", headers=auth).json()
    assert mine["stage"] == "deferred" and mine["completed_at"] is None
    with tenant_session(tid, app_engine) as s:
        assert s.get(Customer, cid).name != "[redacted]"  # nothing was erased
        row = s.get(DataRequest, uuid.UUID(req["id"]))
        assert row.status == "deferred"


def test_done_stage_text_and_dates(app_engine, tid, people):
    cid, _ = people()
    now = datetime.now(UTC)
    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    row = DataRequest(  # never stored: the view only reads the row
        id=uuid.uuid4(),
        tenant_id=tid,
        customer_id=cid,
        kind="erasure",
        status="completed",
        completed_at=now,
        created_at=now - timedelta(days=2),
    )
    body = erasure_info.view(row, settings, "en")
    assert body["stage"] == "done" and body["stage_label"] == "Done"
    assert "erased on" in body["stage_text"] and body["can_withdraw"] is False
    assert body["expected_by"] is None  # no promise once finished


# -- withdrawing --------------------------------------------------------------------------


def test_customer_can_withdraw_before_it_runs_and_ask_again(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _request(api, auth)
    r = api.post("/me/erasure-request/cancel", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == "withdrawn" and body["can_withdraw"] is False
    assert body["expected_by"] is None
    assert api.post("/me/erasure-request/cancel", headers=auth).json()["stage"] == "withdrawn"
    with tenant_session(tid, app_engine) as s:
        events = s.scalars(
            select(AuditEvent.event).where(AuditEvent.entity_id == uuid.UUID(req["id"]))
        ).all()
        assert events.count("privacy.erasure_withdrawn") == 1
    # A person approving a withdrawn request changes nothing.
    assert _approve(api, hq, req["id"])["status"] == "withdrawn"
    with tenant_session(tid, app_engine) as s:
        assert s.get(Customer, cid).name == "Real Person"
    fresh = _request(api, auth)  # asking again is a new request
    assert fresh["id"] != req["id"] and fresh["stage"] == "received"


def test_withdrawing_a_deferred_request_works_and_a_done_one_is_refused(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people()
    assert api.post("/me/erasure-request/cancel", headers=auth).status_code == 404  # none yet
    with tenant_session(tid, app_engine) as s:
        _case(s, tid, made, SimpleId(cid), status="open", age_days=400, ticket="open")
    assert _request(api, auth)["stage"] == "deferred"
    assert api.post("/me/erasure-request/cancel", headers=auth).json()["stage"] == "withdrawn"

    cid2, auth2 = people()
    _erasable(app_engine, tid, made, cid2)
    hq = staff(api, tenant, slug, "hq_owner")
    done = _approve(api, hq, _request(api, auth2)["id"])
    assert done["status"] == "completed"
    # The signed-in session ends with the erasure, so a late withdrawal cannot even sign in.
    assert api.post("/me/erasure-request/cancel", headers=auth2).status_code == 401
    with tenant_session(tid, app_engine) as s:
        row = s.get(DataRequest, uuid.UUID(done["id"]))
        out = privacy.withdraw_erasure(s, tid, row.customer_id)
        assert out.status == "completed"  # unchanged: the route turns this into 409


# -- who may call what --------------------------------------------------------------------


@pytest.mark.parametrize("role", ["hq_owner", "location_manager"])
def test_staff_get_403_on_the_new_customer_endpoints(api, tenant, slug, role):
    try:
        auth = staff(api, tenant, slug, role)
    except StopIteration:
        pytest.skip("no such role in this tenant")
    assert api.get("/me/erasure-info", headers=auth).status_code == 403
    assert api.post("/me/erasure-request/cancel", headers=auth).status_code == 403


def test_anonymous_is_refused(api):
    assert api.get("/me/erasure-info").status_code in (401, 403)
    assert api.post("/me/erasure-request/cancel").status_code in (401, 403)


def test_one_customer_never_sees_or_withdraws_anothers_request(api, app_engine, tid, made, people):
    a, auth_a = people()
    _, auth_b = people()
    _erasable(app_engine, tid, made, a)
    req = _request(api, auth_a)
    assert api.get("/me/erasure-request", headers=auth_b).json() is None
    assert api.post("/me/erasure-request/cancel", headers=auth_b).status_code == 404
    assert api.get("/me/erasure-request", headers=auth_a).json()["id"] == req["id"]


def test_another_tenants_owner_gets_404_for_the_request(api, app_engine, tid, made, people, tenant):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    req = _request(api, auth)
    other = next(p for p in tenant_dirs() if p.name != tenant.name)
    hq_other = staff(api, other, load_tenant(other).slug, "hq_owner")
    assert api.post(f"/data-requests/{req['id']}/approve", headers=hq_other).status_code == 404


# -- copy ---------------------------------------------------------------------------------


def test_every_erasure_key_has_all_three_languages():
    keys = [k for k in TEMPLATES if k.startswith("erase.")]
    assert keys
    for key in keys:
        for lang in LANGUAGES:
            assert TEMPLATES[key].get(lang, "").strip(), (key, lang)


def test_reason_copy_matches_the_staff_wording_in_english():
    for code, text in privacy.REASONS.items():
        assert t(f"erase.reason.{code}", "en", date="2027-01-01") == text.format(date="2027-01-01")


def test_copy_follows_the_customers_language(api, app_engine, tid, people):
    cid, auth = people()
    seen = {}
    for lang in LANGUAGES:
        with tenant_session(tid, app_engine) as s:
            s.get(Customer, cid).preferred_language = lang
        body = _info(api, auth)
        assert body["language"] == lang
        seen[lang] = body["headings"]["remove"]
    assert len(set(seen.values())) == 3


def test_copy_has_no_guilt_or_dashes():
    for key, variants in TEMPLATES.items():
        if key.startswith("erase."):
            for text in variants.values():
                assert "—" not in text and "–" not in text, key
                assert "sorry to see you go" not in text.lower(), key
