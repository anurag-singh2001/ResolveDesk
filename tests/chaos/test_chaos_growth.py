"""Chaos for growth campaign sends (S5.3, PROJECT.md section 15), for every tenant with growth on.

One approved campaign is sent while the messaging provider times out, is unavailable, and
accepts-then-times-out; several workers run the same campaign at once; a worker is killed before
and after handing a message to the provider; one treatment member withdraws marketing consent
mid-way. Then chaos goes off and the campaign is re-run until nobody is outstanding. Checked
against the provider's own records (its operations by idempotency key):

- exactly one provider message per treatment member who still had consent
- none to the holdout, none to the member who withdrew before their send
- every treatment member ends in a final send_status (never silently lost), and send_status
  only ever moved forward
- the campaign ends `sent`; another tenant's outbox is untouched
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, update

from app.connectors.mock_connectors import MockMessagingConnector
from app.core.db import tenant_session
from app.core.models import Campaign, CampaignMember, Consent, Customer, Signal
from app.core.tenancy import tenant_id_for
from app.modules.growth import campaigns as camp
from app.modules.growth.executor import execute_campaign
from mocks.base import Chaos
from mocks.registry import get_mock, merchant_id_for
from tests.integration.test_growth import (  # noqa: F401  (gt is a fixture)
    approvers,
    decide_as,
    gt,
    make_signal,
    propose_for,
    third_party,
)

pytestmark = pytest.mark.chaos

WORKERS = 4
CHAOS = Chaos(
    timeout_rate=0.3,
    transient_error_rate=0.2,
    accept_then_timeout_rate=0.2,
    seed=777,
)
# Forward order of send_status. Equal rank = either may follow the other (a retry can turn
# `processing` back into `unknown`); a final status never changes.
RANK = {"pending": 0, "submitted": 1, "unknown": 2, "processing": 2, "succeeded": 3, "failed": 3}


class WorkerKilled(BaseException):
    """The process running the send died here (BaseException: no `except Exception` saves it)."""


class Observer:
    """Polls every member's send_status in its own session and keeps each one's history."""

    def __init__(self, engine, tid, campaign_id):
        self._args = (engine, tid, campaign_id)
        self.history: dict = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def sample(self):
        engine, tid, cid = self._args
        with tenant_session(tid, engine) as s:
            for member, status in s.execute(
                select(CampaignMember.id, CampaignMember.send_status).where(
                    CampaignMember.campaign_id == cid
                )
            ):
                seq = self.history.setdefault(member, [])
                if not seq or seq[-1] != status:
                    seq.append(status)

    def _run(self):
        while not self._stop.is_set():
            self.sample()
            time.sleep(0.02)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        self.sample()


def _run(engine, tid, cid):
    """One worker run; a killed worker just dies."""
    try:
        return execute_campaign(engine, tid, cid)
    except WorkerKilled:
        return None


def test_campaign_send_survives_messaging_chaos(
    app_engine,
    maint_engine,
    seeded_history,
    gt,  # noqa: F811
    monkeypatch,
):
    cfg, tid, as_of = gt
    if not cfg.feature_flags.get("growth"):
        pytest.skip("growth is off for this tenant")
    others = [n for n, c in seeded_history.items() if c.slug != cfg.slug]
    other_merchant = (
        merchant_id_for(tenant_id_for(seeded_history[others[0]].slug)) if others else None
    )
    msg = get_mock("messaging")
    merchant = merchant_id_for(tid)

    signal_id = make_signal(app_engine, tid, as_of)
    with tenant_session(tid, app_engine) as s:
        loc = s.get(Signal, signal_id).location_id
    hq, other = approvers(app_engine, cfg, tid, loc)
    try:
        cid, _ = propose_for(
            app_engine, tid, signal_id, third_party(app_engine, cfg, tid, loc, hq, other)
        )
    except Exception:
        pytest.skip("history too small for an audience at this scale")
    decide_as(app_engine, tid, hq, cid)
    assert decide_as(app_engine, tid, other, cid) is True

    with tenant_session(tid, app_engine) as s:
        members = camp.members_of(s, s.get(Campaign, cid))
        treatment = {
            m.customer_id: (m.id, m.idempotency_key) for m in members if m.arm == "treatment"
        }
        holdout = {m.customer_id: m.id for m in members if m.arm == "holdout"}
        holdout_status = {m.id: m.send_status for m in members if m.arm == "holdout"}
        phones = {i: p for i, p in s.execute(select(Customer.id, Customer.phone))}
    if len(treatment) < 4:
        pytest.skip("treatment arm too small for a chaos run at this scale")
    assert all(k == f"C-{cid}:{c}:send:1" for c, (_, k) in treatment.items())
    other_before = len(msg.operations(other_merchant)) if other_merchant else 0

    msg.set_chaos(CHAOS, merchant)
    withdrawn = None
    real_send = MockMessagingConnector.send
    try:
        with Observer(app_engine, tid, cid) as obs:
            # 1. A worker dies handing over its 3rd message: the rest of its list is never sent.
            calls = {"n": 0}
            lock = threading.Lock()

            def die_on_third(self, *a, **k):
                with lock:
                    calls["n"] += 1
                    n = calls["n"]
                if n == 3:
                    raise WorkerKilled
                return real_send(self, *a, **k)

            with monkeypatch.context() as m:
                m.setattr(MockMessagingConnector, "send", die_on_third)
                assert _run(app_engine, tid, cid) is None

            # 2. One member who has not been sent anything withdraws marketing consent.
            unsent = [c for c, (_, k) in treatment.items() if msg.get_message(merchant, k) is None]
            assert unsent, "the killed worker should have left members unsent"
            withdrawn = unsent[0]
            with tenant_session(tid, maint_engine) as s:
                s.execute(
                    update(Consent)
                    .where(
                        Consent.customer_id == withdrawn,
                        Consent.channel == "whatsapp",
                        Consent.purpose == "marketing",
                    )
                    .values(granted=False)
                )

            # 3. Several workers at once, one of them dying right after the provider took a
            #    message (the message is out; its status is never written by that worker).
            died = {"once": False}

            def die_after_first(self, *a, **k):
                result = real_send(self, *a, **k)
                with lock:
                    first, died["once"] = not died["once"], True
                if first:
                    raise WorkerKilled
                return result

            with monkeypatch.context() as m:
                m.setattr(MockMessagingConnector, "send", die_after_first)
                with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                    list(pool.map(lambda _: _run(app_engine, tid, cid), range(WORKERS)))

            # 4. Chaos off: re-run until nobody is outstanding.
            msg.set_chaos(Chaos(), merchant)
            final = None
            for _ in range(10):
                final = execute_campaign(app_engine, tid, cid)
                if final.outstanding == 0:
                    break
    finally:
        msg.set_chaos(Chaos(), merchant)
        with tenant_session(tid, maint_engine) as s:
            if withdrawn is not None:
                s.execute(
                    update(Consent)
                    .where(
                        Consent.customer_id == withdrawn,
                        Consent.channel == "whatsapp",
                        Consent.purpose == "marketing",
                    )
                    .values(granted=True)
                )

    # --- invariants ----------------------------------------------------------------------
    assert final.outcome == "sent" and final.outstanding == 0
    expected = {k: phones[c] for c, (_, k) in treatment.items() if c != withdrawn}
    ops = msg.operations(merchant)
    by_key = {}
    for op in ops:
        assert op.idempotency_key not in by_key, "two provider operations for one key"
        by_key[op.idempotency_key] = op
    assert set(by_key) == set(expected)  # exactly the consenting treatment members
    for key, phone in expected.items():
        assert by_key[key].status == "succeeded" and by_key[key].request.to == phone
    sent_to = [r.to for r in msg.outbox(merchant)]
    assert sorted(sent_to) == sorted(expected.values())  # zero duplicates
    assert not by_key.keys() & {f"C-{cid}:{c}:send:1" for c in holdout}  # no holdout key sent
    assert treatment[withdrawn][1] not in by_key  # withdrew before their send: nothing went out

    with tenant_session(tid, app_engine) as s:
        c = s.get(Campaign, cid)
        assert c.status == "sent" and c.sent_at is not None
        final_status = {m.id: m.send_status for m in camp.members_of(s, c)}
    for cust, (mid, _key) in treatment.items():
        want = "failed" if cust == withdrawn else "succeeded"
        assert final_status[mid] == want, (cust, final_status[mid])
    assert {final_status[m] for m in holdout.values()} <= set(holdout_status.values())
    assert {mid: final_status[mid] for mid in holdout_status} == holdout_status  # holdout untouched

    for mid, seq in obs.history.items():  # statuses only moved forward
        ranks = [RANK[x] for x in seq]
        assert ranks == sorted(ranks), (mid, seq)
        if seq[-1] in ("succeeded", "failed"):
            assert [x for x in seq if x in ("succeeded", "failed")] == [seq[-1]]
    if other_merchant:
        assert len(msg.operations(other_merchant)) == other_before  # nothing leaked across tenants
