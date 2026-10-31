# ruff: noqa: F811, F401
"""S8.8 / P4: the one "your erasure is complete" message.

Runs for every tenant and names none. The rules under test: sent only after the executor
succeeded, once, to a destination captured at request time in a short-lived outbox row that is
deleted when the outcome is final or after 7 days, never claiming "sent" for an unknown answer,
no personal detail in the audit trail, and a request with nowhere to send says so.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES, TEMPLATES
from app.core.models import AuditEvent, Customer, DataRequest, ErasureNotice
from app.engine import data_rights as privacy
from app.engine import erasure_notice
from mocks.base import Chaos
from mocks.registry import get_mock, merchant_id_for, reset_mocks, set_chaos
from tests.integration import test_retention as ret
from tests.integration.test_data_rights import (
    _approve,
    _erasable,
    people,
    slug,
    staff,
)
from tests.integration.test_retention import KEPT

made = ret.made
tid = ret.tid


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


def outbox(tenant_id):
    return get_mock("messaging").outbox(merchant_id_for(tenant_id))


def _ask(api, auth, **body):
    r = api.post("/me/erasure-request", headers=auth, json=body or None)
    assert r.status_code == 201, r.text
    return r.json()


def _notice(app_engine, tid, request_id):
    with tenant_session(tid, app_engine) as s:
        row = s.scalar(select(ErasureNotice).where(ErasureNotice.request_id == request_id))
        if row is None:
            return None
        cols = ("channel", "destination", "state", "expires_at", "created_at", "language")
        return SimpleNamespace(**{c: getattr(row, c) for c in cols})


def _outcome(app_engine, tid, request_id):
    with tenant_session(tid, app_engine) as s:
        return s.get(DataRequest, request_id).completion_message


def test_the_destination_is_captured_at_request_time_for_seven_days(
    api, app_engine, tid, made, people
):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    req = _ask(api, auth, notify_via="email")
    rid = uuid.UUID(req["id"])
    row = _notice(app_engine, tid, rid)
    assert (row.channel, row.destination, row.state) == ("email", KEPT[2], "queued")
    assert abs((row.expires_at - row.created_at) - timedelta(days=7)) < timedelta(minutes=5)
    assert outbox(tid) == []  # nothing is sent at request time
    assert req["completion_message"] is None


def test_default_is_the_phone_else_the_email(api, app_engine, tid, made, people):
    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    rid = uuid.UUID(_ask(api, auth)["id"])
    assert _notice(app_engine, tid, rid).channel == "phone"
    # A pick the customer has no value for falls back to what they do have.
    cid2, auth2 = people()
    _erasable(app_engine, tid, made, cid2)
    with tenant_session(tid, app_engine) as s:
        s.get(Customer, cid2).phone = None
    rid2 = uuid.UUID(_ask(api, auth2, notify_via="phone")["id"])
    assert _notice(app_engine, tid, rid2).channel == "email"


def test_the_message_goes_out_once_after_success_and_the_destination_is_deleted(
    api, app_engine, tid, made, people, tenant, slug
):
    cid, auth = people("Quentin Quimby")
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    req = _ask(api, auth, notify_via="email")
    assert outbox(tid) == []
    done = _approve(api, hq, req["id"])  # the background send runs after the commit
    assert done["status"] == "completed"
    sent = outbox(tid)
    assert len(sent) == 1 and sent[0].to == KEPT[2] and sent[0].template == "erasure_completed"
    params = dict(sent[0].params)
    body = params["body"]
    assert req["id"].split("-")[0].upper() in body
    assert "Data Protection Board" in body and "removed" in body and "kept" in body
    assert "Quentin" not in body and "₹" not in body  # no name, order or amount

    rid = uuid.UUID(req["id"])
    assert _notice(app_engine, tid, rid) is None  # the destination is gone
    assert _outcome(app_engine, tid, rid) == "sent"
    # Idempotent: approving again, or sending again, sends nothing more.
    _approve(api, hq, req["id"])
    assert erasure_notice.send_completion_notice(app_engine, tid, rid) == "sent"
    assert len(outbox(tid)) == 1
    # The receipt carries the outcome only, never the destination.
    with tenant_session(tid, app_engine) as s:
        events = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == rid, AuditEvent.event == "privacy.erasure_notice"
            )
        ).all()
        assert [e.payload for e in events] == [{"outcome": "sent"}]
        asked = s.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == rid, AuditEvent.event == "privacy.erasure_requested"
            )
        )
        assert asked.payload["notify_channel"] == "email"
        assert KEPT[2] not in str(asked.payload) and KEPT[1] not in str(asked.payload)


def test_nothing_is_sent_before_the_executor_has_succeeded(api, app_engine, tid, made, people):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    rid = uuid.UUID(_ask(api, auth)["id"])  # pending approval: not erased yet
    assert erasure_notice.send_completion_notice(app_engine, tid, rid) is None
    assert erasure_notice.sweep_notices(app_engine, tid) == []
    assert outbox(tid) == [] and _notice(app_engine, tid, rid) is not None


def test_withdrawing_deletes_the_destination_and_nothing_is_sent(
    api, app_engine, tid, made, people
):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    rid = uuid.UUID(_ask(api, auth)["id"])
    assert api.post("/me/erasure-request/cancel", headers=auth).status_code == 200
    assert _notice(app_engine, tid, rid) is None
    assert erasure_notice.send_completion_notice(app_engine, tid, rid) is None
    assert outbox(tid) == []


def test_an_unknown_provider_answer_is_never_reported_as_sent(
    api, app_engine, tid, made, people, tenant, slug
):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    set_chaos("messaging", Chaos(timeout_rate=1.0), merchant_id_for(tid))
    req = _ask(api, auth)
    _approve(api, hq, req["id"])
    rid = uuid.UUID(req["id"])
    assert _outcome(app_engine, tid, rid) == "unknown"
    assert _notice(app_engine, tid, rid) is None  # final: the destination goes anyway
    assert outbox(tid) == []


def test_a_provider_that_is_not_answering_yet_is_retried_by_the_sweeper(
    api, app_engine, tid, made, people, tenant, slug
):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    hq = staff(api, tenant, slug, "hq_owner")
    set_chaos("messaging", Chaos(transient_error_rate=1.0), merchant_id_for(tid))
    req = _ask(api, auth)
    _approve(api, hq, req["id"])
    rid = uuid.UUID(req["id"])
    assert _outcome(app_engine, tid, rid) is None  # not final: still queued for a retry
    assert _notice(app_engine, tid, rid).state == "sending"
    reset_mocks()  # the provider recovers
    assert erasure_notice.sweep_notices(app_engine, tid) == [str(rid)]
    assert _outcome(app_engine, tid, rid) == "sent" and len(outbox(tid)) == 1
    assert _notice(app_engine, tid, rid) is None


def test_after_seven_days_the_destination_is_removed_and_no_message_is_sent(
    api, app_engine, tid, made, people
):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    rid = uuid.UUID(_ask(api, auth)["id"])  # still waiting for a person
    later = datetime.now(UTC) + timedelta(days=8)
    erasure_notice.sweep_notices(app_engine, tid, later)
    assert _notice(app_engine, tid, rid) is None  # purged though never sent
    # If it completes after that, there is nowhere to send: recorded as expired, never as sent.
    with tenant_session(tid, app_engine) as s:
        privacy.run_erasure(s, tid, rid, None, later)
    assert erasure_notice.send_completion_notice(app_engine, tid, rid, later) == "expired"
    assert outbox(tid) == [] and _outcome(app_engine, tid, rid) == "expired"


def test_a_completed_request_whose_seven_days_ran_out_expires(api, app_engine, tid, made, people):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    rid = uuid.UUID(_ask(api, auth)["id"])
    with tenant_session(tid, app_engine) as s:
        privacy.run_erasure(s, tid, rid, None, datetime.now(UTC))
        s.execute(
            update(ErasureNotice)
            .where(ErasureNotice.request_id == rid)
            .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
        )
    assert erasure_notice.send_completion_notice(app_engine, tid, rid) == "expired"
    assert _notice(app_engine, tid, rid) is None and outbox(tid) == []


def test_with_nowhere_to_send_the_request_says_so_and_no_row_is_kept(
    api, app_engine, tid, made, people, tenant, slug
):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    with tenant_session(tid, app_engine) as s:
        c = s.get(Customer, cid)
        c.phone = c.email = None
    info = api.get("/me/erasure-info", headers=auth).json()["completion_notice"]
    assert info["channels"] == [] and info["default"] is None and info["text"]
    req = _ask(api, auth)
    assert req["completion_message"] == "none"
    rid = uuid.UUID(req["id"])
    assert _notice(app_engine, tid, rid) is None
    _approve(api, staff(api, tenant, slug, "hq_owner"), req["id"])
    assert outbox(tid) == [] and _outcome(app_engine, tid, rid) == "none"


def test_the_info_names_the_channels_the_customer_holds(api, people):
    _, auth = people()
    block = api.get("/me/erasure-info", headers=auth).json()["completion_notice"]
    assert block["channels"] == ["phone", "email"] and block["default"] == "phone"
    assert "7 days" in block["text"] and set(block["labels"]) == {"phone", "email"}


def test_a_bad_channel_is_refused(api, people):
    _, auth = people()
    r = api.post("/me/erasure-request", headers=auth, json={"notify_via": "carrier-pigeon"})
    assert r.status_code == 422


def test_the_completion_text_is_a_template_in_every_language():
    settings = {
        "privacy_contact_name": "Desk",
        "privacy_contact_email": "desk@example.test",
        "grievance_target_days": 30,
        "payment_retention_years": 8,
    }

    for lang in LANGUAGES:
        text = erasure_notice.completion_text(settings, lang, uuid.uuid4())
        assert "{" not in text and "Desk (desk@example.test)" in text and "8" in text
        assert "Data Protection Board" in text or "Board" in text or "बोर्ड" in text
        bare = erasure_notice.completion_text(
            {**settings, "privacy_contact_email": "", "privacy_contact_name": ""},
            lang,
            uuid.uuid4(),
        )
        assert "desk@" not in bare and "{" not in bare
    for key in ("notice.done", "notice.kept", "notice.contact", "notice.board"):
        assert set(TEMPLATES[key]) == set(LANGUAGES)


def test_other_customers_cannot_see_or_use_a_request_they_do_not_own(
    api, app_engine, tid, made, people
):

    cid, auth = people()
    _erasable(app_engine, tid, made, cid)
    rid = uuid.UUID(_ask(api, auth)["id"])
    _, other = people()
    assert api.get("/me/erasure-request", headers=other).json() is None
    assert _notice(app_engine, tid, rid) is not None
