# ruff: noqa: F811
"""S8.5b: the frequency cap the privacy page promises is enforced when the message is sent.

"At most one offer message in 30 days" must hold even when audience selection was done earlier,
two campaigns are approved together, or two customer rows share a phone. Runs for every tenant
and names none. The send-time check is in app/modules/growth/executor.py.
"""

import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.db import tenant_session
from app.core.models import CampaignMember, Customer
from app.modules.growth import campaigns as camp
from app.modules.growth.campaigns import FREQUENCY_CAP_DAYS
from app.modules.growth.executor import execute_campaign
from tests.integration.test_growth import approved_campaign, gt, outbox  # noqa: F401


def _members(app_engine, tid, cid):
    with tenant_session(tid, app_engine) as s:
        return {
            m.customer_id: (m.send_status, m.skip_reason, m.claimed_at)
            for m in camp.members_of(s, s.get(camp.Campaign, cid))
            if m.arm == "treatment"
        }


def _two_campaigns(app_engine, cfg, tid, as_of):
    """Two approved, unsent campaigns (A, then B on the next window). Returns (a, b)."""
    a, _, _ = approved_campaign(app_engine, cfg, tid, as_of)
    b, _, _ = approved_campaign(app_engine, cfg, tid, as_of - timedelta(days=1))
    return a, b


def _earlier_send(maint_engine, tid, campaign_id, customer, claimed_at):
    """A message to `customer` that another (already sent) campaign made at `claimed_at`."""
    with tenant_session(tid, maint_engine) as s:
        s.add(
            CampaignMember(
                tenant_id=tid,
                campaign_id=campaign_id,
                customer_id=customer,
                arm="treatment",
                send_status="succeeded",
                claimed_at=claimed_at,
                idempotency_key=f"C-{campaign_id}:{customer}:send:1",
            )
        )


def _phones(app_engine, tid):
    with tenant_session(tid, app_engine) as s:
        return {i: p for i, p in s.execute(select(Customer.id, Customer.phone))}


@contextmanager
def _phone_set(app_engine, maint_engine, tid, customer, phone):
    """Give a seeded customer another phone for one test, and put the seed back."""
    with tenant_session(tid, app_engine) as s:
        original = s.get(Customer, customer).phone
    with tenant_session(tid, maint_engine) as s:
        s.execute(update(Customer).where(Customer.id == customer).values(phone=phone))
    try:
        yield
    finally:
        with tenant_session(tid, maint_engine) as s:
            s.execute(update(Customer).where(Customer.id == customer).values(phone=original))


def test_a_customer_already_messaged_by_another_campaign_is_skipped(app_engine, maint_engine, gt):
    cfg, tid, as_of = gt
    a, b = _two_campaigns(app_engine, cfg, tid, as_of)
    assert execute_campaign(app_engine, tid, a).outcome == "sent"  # A is now `sent`
    in_b = _members(app_engine, tid, b)
    victim = next((c for c in sorted(in_b) if c not in _members(app_engine, tid, a)), None)
    if victim is None:
        pytest.skip("campaign B has no customer outside campaign A at this scale")
    _earlier_send(maint_engine, tid, a, victim, datetime.now(UTC) - timedelta(days=2))
    before = len(outbox(tid))
    execute_campaign(app_engine, tid, b)
    status, reason, _ = _members(app_engine, tid, b)[victim]
    assert (status, reason) == ("skipped", "frequency_cap")  # not `failed`
    assert _phones(app_engine, tid)[victim] not in [r.to for r in outbox(tid)[before:]]


def test_a_send_older_than_the_cap_does_not_block_a_new_one(app_engine, maint_engine, gt):
    cfg, tid, as_of = gt
    a, b = _two_campaigns(app_engine, cfg, tid, as_of)
    execute_campaign(app_engine, tid, a)
    victim = next(
        (c for c in sorted(_members(app_engine, tid, b)) if c not in _members(app_engine, tid, a)),
        None,
    )
    if victim is None:
        pytest.skip("campaign B has no customer outside campaign A at this scale")
    old = datetime.now(UTC) - timedelta(days=FREQUENCY_CAP_DAYS + 1)
    _earlier_send(maint_engine, tid, a, victim, old)  # the earlier message was 31 days ago
    execute_campaign(app_engine, tid, b)
    assert _members(app_engine, tid, b)[victim][0] == "succeeded"


def test_two_campaigns_running_at_the_same_time_send_once_to_one_phone(
    app_engine, maint_engine, gt
):
    cfg, tid, as_of = gt
    a, b = _two_campaigns(app_engine, cfg, tid, as_of)
    in_a, in_b = sorted(_members(app_engine, tid, a)), sorted(_members(app_engine, tid, b))
    ca = in_a[0]
    cb = next((c for c in in_b if c != ca), None)
    if cb is None:
        pytest.skip("no second customer to share a phone with")
    shared = _phones(app_engine, tid)[ca]
    with _phone_set(app_engine, maint_engine, tid, cb, shared):  # a household, two rows
        threads = [
            threading.Thread(target=execute_campaign, args=(app_engine, tid, c)) for c in (a, b)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert [r.to for r in outbox(tid)].count(shared) == 1
    states = [_members(app_engine, tid, a).get(ca), _members(app_engine, tid, b).get(cb)]
    assert sorted(st[0] for st in states if st) in (["skipped", "succeeded"], ["succeeded"])


def test_two_customer_rows_sharing_a_phone_get_one_message(app_engine, maint_engine, gt):
    cfg, tid, as_of = gt
    cid, _, _ = approved_campaign(app_engine, cfg, tid, as_of)
    members = _members(app_engine, tid, cid)
    if len(members) < 2:
        pytest.skip("campaign has fewer than two treatment members")
    first, second = sorted(members)[:2]
    phone = _phones(app_engine, tid)[first]
    written_differently = " +91 " + phone[-10:]
    with _phone_set(app_engine, maint_engine, tid, second, written_differently):
        execute_campaign(app_engine, tid, cid)
    states = _members(app_engine, tid, cid)
    assert sorted(states[c][0] for c in (first, second)) == ["skipped", "succeeded"]
    sent_to = [r.to for r in outbox(tid)]
    assert sent_to.count(phone) + sent_to.count(written_differently) == 1


def test_a_rerun_of_the_same_campaign_is_not_blocked_by_its_own_claims(app_engine, gt):
    cfg, tid, as_of = gt
    cid, _, _ = approved_campaign(app_engine, cfg, tid, as_of)
    first = execute_campaign(app_engine, tid, cid)
    again = execute_campaign(app_engine, tid, cid)
    assert first.succeeded == again.succeeded and again.outstanding == 0
    assert not any(v[0] == "skipped" for v in _members(app_engine, tid, cid).values())
