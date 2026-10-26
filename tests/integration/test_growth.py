"""E8 growth: signal job, audience + dual-approved campaign, idempotent sends, verdict.

Runs for every tenant folder and never names one: what a tenant has planted comes from its
simulation config, and who may approve comes from its users' roles.
"""

import threading
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.api.deps import get_clock
from app.core.db import tenant_session
from app.core.models import (
    GROWTH_MODELS,
    Campaign,
    CampaignMember,
    Consent,
    Customer,
    Location,
    PlaybookEntry,
    Signal,
    Transaction,
    User,
)
from app.core.tenancy import load_context, tenant_id_for
from app.engine.proposals import ProposalError
from app.modules.growth import campaigns as camp
from app.modules.growth import signals as sig
from app.modules.growth.executor import execute_campaign
from app.modules.growth.verdict import MIN_ARM_N, NotReady, compute_verdict, measure
from mocks.registry import get_mock, merchant_id_for, reset_mocks
from simulator.generate import LOCAL_TZ
from simulator.growth import simulate_post_campaign_orders
from tests.helpers import login


@pytest.fixture
def gt(seeded_history, tenant, app_engine, maint_engine):
    """(cfg, tenant_id, as_of) with the tenant's growth rows, and the orders the growth
    simulator adds, cleared before and after (so later tests see the seeded history only)."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)

    def clear():
        with tenant_session(tid, maint_engine) as s:
            for model in reversed(GROWTH_MODELS):
                s.execute(delete(model).where(model.tenant_id == tid))
            s.execute(
                delete(Transaction).where(
                    Transaction.tenant_id == tid, Transaction.source == "sim_growth"
                )
            )

    clear()
    reset_mocks()
    end = cfg.simulation.end_date + timedelta(days=1)
    yield cfg, tid, datetime.combine(end, time(0), LOCAL_TZ)
    clear()
    reset_mocks()


def ctx_of(engine, tid, email):
    with tenant_session(tid, engine) as s:
        uid = s.scalar(select(User.id).where(User.email == email))
        return load_context(s, tid, uid)


def staff_ctxs(engine, cfg, tid):
    out = [ctx_of(engine, tid, u.email) for u in cfg.users if u.role != "customer"]
    return out


def make_signal(engine, tid, as_of):
    """A stored signal at the location with the largest lapsed audience (same for any tenant:
    the campaign steps don't depend on a drop having been planted)."""
    with tenant_session(tid, engine) as s:
        best = max(
            s.scalars(select(Location.id)),
            key=lambda loc: len(camp.lapsed_audience(s, tid, loc, as_of)),
        )
        r = sig.read_location(s, tid, best, as_of)
        diagnosis = sig.template_diagnosis(sig.gather_evidence(s, tid, r))
        return sig.store_signal(s, tid, r, diagnosis, "template").id


def approvers(engine, cfg, tid, location_id):
    """(an hq_owner, a different staff user who may act on the location)."""
    ctxs = staff_ctxs(engine, cfg, tid)
    hq = next(c for c in ctxs if c.role == "hq_owner")
    other = next(
        (
            c
            for c in ctxs
            if c.user_id != hq.user_id and c.role != "hq_owner" and c.can_see_location(location_id)
        ),
        None,
    ) or next((c for c in ctxs if c.user_id != hq.user_id and c.role == "hq_owner"), None)
    if other is None:
        pytest.skip("tenant has no second staff user for this location")
    return hq, other


def propose_for(engine, tid, signal_id, ctx, now=None, **kw):
    with tenant_session(tid, engine) as s:
        c = camp.propose(s, ctx, signal_id, now or datetime.now(UTC), **kw)
        return c.id, c.payload_hash


def decide_as(engine, tid, ctx, campaign_id, now=None, decision="approved"):
    with tenant_session(tid, engine) as s:
        return camp.decide(s, ctx, campaign_id, decision, now or datetime.now(UTC))[1]


def outbox(tid):
    return get_mock("messaging").outbox(merchant_id_for(tid))


# -- E8.1 ------------------------------------------------------------------------------------


def test_planted_drop_is_found_and_nothing_else(app_engine, gt):
    cfg, tid, as_of = gt
    planted = {p.location for p in cfg.simulation.problems if p.kind == "repeat_drop"}
    with tenant_session(tid, app_engine) as s:
        slug_of = {i: slug for i, slug in s.execute(select(Location.id, Location.slug))}
        first = sig.run_signal_job(s, tid, as_of)
        found = {slug_of[x.location_id] for x in first}
        ids = {x.id for x in first}
        facts = [(x.drop_bp, x.diagnosis["findings"], x.diagnosis_source) for x in first]
    assert found == planted  # the planted drop is detected; nowhere else raises a false alarm
    for drop_bp, findings, source in facts:
        assert drop_bp >= sig.MIN_DROP_BP and findings
        assert source == "template"
    # Re-running (job, and the three-phase nightly variant) stores nothing new.
    assert set(sig.run_nightly(app_engine, tid, as_of)) == ids
    with tenant_session(tid, app_engine) as s:
        assert s.scalar(select(func.count()).select_from(Signal)) == len(ids)


def test_signal_needs_a_real_drop_not_a_small_sample():
    big = sig.Reading(uuid.uuid4(), *(datetime.now(UTC),) * 3, 200, 200, 4000, 3000, 400)
    assert big.flagged
    # Same drop but too few orders: no alarm.
    small = sig.Reading(uuid.uuid4(), *(datetime.now(UTC),) * 3, 10, 10, 4000, 3000, 400)
    assert not small.flagged
    # A 3-point dip is not worth acting on even with plenty of orders.
    dip = sig.Reading(uuid.uuid4(), *(datetime.now(UTC),) * 3, 5000, 5000, 4000, 3700, 400)
    assert not dip.flagged
    # A big-looking drop that isn't significant (z below 1.64) is not flagged.
    noisy = sig.Reading(uuid.uuid4(), *(datetime.now(UTC),) * 3, 40, 40, 4000, 3000, 100)
    assert not noisy.flagged


# -- E8.2 ------------------------------------------------------------------------------------


def test_split_is_deterministic_and_never_overlaps():
    ids = [uuid.UUID(int=i) for i in range(1, 51)]
    t, h = camp.split_audience(ids, "seed", 10)
    assert (t, h) == camp.split_audience(list(reversed(ids)), "seed", 10)
    assert len(h) == 5 and not set(t) & set(h) and sorted(t + h) == ids
    assert camp.split_audience(ids, "other", 10) != (t, h)
    t2, h2 = camp.split_audience(ids[:2], "seed", 10)  # tiny audience: still one of each
    assert len(t2) == 1 and len(h2) == 1


def test_dual_approval_rule():
    now = datetime.now(UTC)

    def a(user, role):
        from app.core.models import CampaignApproval

        return CampaignApproval(decided_by=user, role=role, decision="approved", expires_at=now)

    u1, u2 = uuid.uuid4(), uuid.uuid4()
    assert not camp.dual_approved([a(u1, "hq_owner")])
    assert not camp.dual_approved([a(u1, "hq_owner"), a(u1, "hq_owner")])  # one person twice
    assert not camp.dual_approved([a(u1, "franchisee_owner"), a(u2, "location_manager")])
    assert camp.dual_approved([a(u1, "hq_owner"), a(u2, "location_manager")])


def test_audience_is_consented_capped_and_bound_to_a_hash(app_engine, gt):
    cfg, tid, as_of = gt
    signal_id = make_signal(app_engine, tid, as_of)
    hq = next(c for c in staff_ctxs(app_engine, cfg, tid) if c.role == "hq_owner")
    with tenant_session(tid, app_engine) as s:
        signal = s.get(Signal, signal_id)
        loc = signal.location_id
        audience = camp.lapsed_audience(s, tid, loc, signal.recent_end)
        ok = set(
            s.scalars(
                select(Consent.customer_id).where(Consent.purpose == "marketing", Consent.granted)
            )
        )
        assert {c for c, _ in audience} <= ok  # no marketing consent, no message
    if len(audience) < 2:
        pytest.skip("history too small for an audience at this scale")
    cid, h1 = propose_for(app_engine, tid, signal_id, hq, offer_paise=5000)
    cid2, h2 = propose_for(app_engine, tid, signal_id, hq, offer_paise=9999)  # re-run
    assert (cid, h1) == (cid2, h2)  # one campaign per signal; a re-run changes nothing
    with tenant_session(tid, app_engine) as s:
        c = s.get(Campaign, cid)
        ms = camp.members_of(s, c)
        assert camp.hash_is_intact(s, c)
        assert len({m.customer_id for m in ms}) == len(ms) == len(audience)
        assert {m.arm for m in ms} == {"treatment", "holdout"}
        assert len({m.idempotency_key for m in ms}) == len(ms)
        assert c.budget_paise == 5000 * c.params["treatment_n"]
        # Frequency cap: those customers are not offered a second campaign straight away.
        again = camp.lapsed_audience(s, tid, loc, as_of)
        assert not {x for x, _ in again} & {m.customer_id for m in ms}
        assert s.get(Signal, signal_id).status == "actioned"


def test_budget_cap_refuses_an_oversized_campaign(app_engine, gt):
    cfg, tid, as_of = gt
    signal_id = make_signal(app_engine, tid, as_of)
    hq = next(c for c in staff_ctxs(app_engine, cfg, tid) if c.role == "hq_owner")
    with pytest.raises(ProposalError, match="budget"), tenant_session(tid, app_engine) as s:
        camp.propose(s, hq, signal_id, datetime.now(UTC), offer_paise=10**9)


def test_nothing_is_sent_until_both_approve_then_exactly_once(app_engine, gt):
    cfg, tid, as_of = gt
    signal_id = make_signal(app_engine, tid, as_of)
    with tenant_session(tid, app_engine) as s:
        loc = s.get(Signal, signal_id).location_id
    hq, other = approvers(app_engine, cfg, tid, loc)
    try:
        cid, _ = propose_for(app_engine, tid, signal_id, hq)
    except ProposalError:
        pytest.skip("history too small for an audience at this scale")
    # No approvals, then one, then the same person again: still nothing goes out.
    assert execute_campaign(app_engine, tid, cid).outcome == "refused"
    assert decide_as(app_engine, tid, hq, cid) is False
    with pytest.raises(camp.AlreadyDecided):
        decide_as(app_engine, tid, hq, cid)  # double approve never counts twice
    assert execute_campaign(app_engine, tid, cid).outcome == "refused"
    assert outbox(tid) == []
    # The second, different user completes it.
    assert decide_as(app_engine, tid, other, cid) is True
    with tenant_session(tid, app_engine) as s:
        c = s.get(Campaign, cid)
        treatment = {m.customer_id: m for m in camp.members_of(s, c) if m.arm == "treatment"}
        holdout = [m.customer_id for m in camp.members_of(s, c) if m.arm == "holdout"]
        phones = {i: p for i, p in s.execute(select(Customer.id, Customer.phone))}
    # Re-runs and a race between two workers: still one message per treatment member.
    threads = [
        threading.Thread(target=execute_campaign, args=(app_engine, tid, cid)) for _ in (1, 2)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    first = execute_campaign(app_engine, tid, cid)
    execute_campaign(app_engine, tid, cid)
    sent_to = [r.to for r in outbox(tid)]
    assert first.outcome == "sent" and first.outstanding == 0
    assert sorted(sent_to) == sorted(phones[i] for i in treatment)  # zero duplicates
    assert not {phones[i] for i in holdout} & set(sent_to)  # the holdout is never contacted
    with tenant_session(tid, app_engine) as s:
        c = s.get(Campaign, cid)
        assert c.status == "sent" and c.sent_at is not None
        assert {m.send_status for m in camp.members_of(s, c) if m.arm == "treatment"} == {
            "succeeded"
        }


def test_tampered_or_expired_campaigns_do_not_send(app_engine, maint_engine, gt):
    cfg, tid, as_of = gt
    signal_id = make_signal(app_engine, tid, as_of)
    with tenant_session(tid, app_engine) as s:
        loc = s.get(Signal, signal_id).location_id
    hq, other = approvers(app_engine, cfg, tid, loc)
    try:
        cid, _ = propose_for(app_engine, tid, signal_id, hq)
    except ProposalError:
        pytest.skip("history too small for an audience at this scale")
    now = datetime.now(UTC)
    with pytest.raises(camp.Expired):
        decide_as(app_engine, tid, hq, cid, now=now + timedelta(days=3))
    decide_as(app_engine, tid, hq, cid)
    decide_as(app_engine, tid, other, cid)
    # Approvals expire: a day later the approved campaign refuses to send.
    late = execute_campaign(app_engine, tid, cid, now=now + timedelta(hours=30))
    assert late.outcome == "refused" and outbox(tid) == []
    # Someone edits the offer behind the approvers' backs (owner-level access): refused.
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            update(Campaign)
            .where(Campaign.id == cid)
            .values(params=Campaign.params.concat({"offer_paise": 99999}))
        )
    assert execute_campaign(app_engine, tid, cid).outcome == "refused"
    assert outbox(tid) == []


# -- E8.3 ------------------------------------------------------------------------------------


def test_verdict_rules():
    big_win = compute_verdict(200, 90, 200, 50)
    assert big_win.verdict == "worked" and big_win.uplift_bp == 2000 and "95%" in big_win.note
    assert compute_verdict(200, 50, 200, 90).verdict == "did_not_work"
    small = compute_verdict(10, 9, 3, 0)  # looks great, proves nothing
    assert small.verdict == "inconclusive" and "Too few" in small.note
    noise = compute_verdict(MIN_ARM_N, 8, MIN_ARM_N, 7)
    assert noise.verdict == "inconclusive" and "chance" in noise.note


def test_verdict_after_window_and_playbook_entry(app_engine, gt):
    cfg, tid, as_of = gt
    signal_id = make_signal(app_engine, tid, as_of)
    with tenant_session(tid, app_engine) as s:
        loc = s.get(Signal, signal_id).location_id
    hq, other = approvers(app_engine, cfg, tid, loc)
    try:
        cid, _ = propose_for(app_engine, tid, signal_id, hq)
    except ProposalError:
        pytest.skip("history too small for an audience at this scale")
    with tenant_session(tid, app_engine) as s, pytest.raises(NotReady):
        measure(s, hq, cid, datetime.now(UTC))  # nothing sent yet
    decide_as(app_engine, tid, hq, cid)
    decide_as(app_engine, tid, other, cid)
    execute_campaign(app_engine, tid, cid)
    with tenant_session(tid, app_engine) as s:
        sent_at = s.get(Campaign, cid).sent_at
    with tenant_session(tid, app_engine) as s, pytest.raises(NotReady):
        measure(s, hq, cid, sent_at + timedelta(days=1))  # window still open
    added = simulate_post_campaign_orders(
        app_engine, tid, cid, treatment_rate_bp=9000, holdout_rate_bp=0
    )
    assert added > 0
    after = sent_at + timedelta(days=15)
    with tenant_session(tid, app_engine) as s:
        entry = measure(s, hq, cid, after)
        first = (entry.id, entry.verdict, entry.treatment_n, entry.holdout_n)
        assert entry.treatment_repeat == added and entry.holdout_repeat == 0
        assert entry.uplift_bp > 0
        small = entry.holdout_n < MIN_ARM_N or entry.treatment_n < MIN_ARM_N
        verdict, note = entry.verdict, entry.confidence_note
    with tenant_session(tid, app_engine) as s:
        again = measure(s, hq, cid, after)  # idempotent: the same row comes back
        assert (again.id, again.verdict, again.treatment_n, again.holdout_n) == first
        assert s.scalar(select(func.count()).select_from(PlaybookEntry)) == 1
        assert s.get(Campaign, cid).status == "measured"
        # Honest: a small audience can't be called a win however good the raw numbers look.
        if small:
            assert verdict == "inconclusive" and "Too few" in note


# -- API -------------------------------------------------------------------------------------


def test_growth_api_is_staff_only_and_flag_gated(api, app_engine, gt):
    cfg, tid, as_of = gt
    try:
        hq_email = next(u.email for u in cfg.users if u.role == "hq_owner")
        customer_email = next(u.email for u in cfg.users if u.role == "customer")
        hq = login(api, cfg.slug, hq_email)
        cust = login(api, cfg.slug, customer_email)
        api.app.dependency_overrides[get_clock] = lambda: as_of  # after login: tokens use real time
        assert api.get("/growth/signals").status_code == 401
        enabled = bool(cfg.feature_flags.get("growth"))
        if not enabled:
            assert api.get("/growth/signals", headers=hq).status_code == 404
            return
        assert api.get("/growth/signals", headers=cust).status_code == 403
        assert api.get(f"/growth/campaigns/{uuid.uuid4()}", headers=hq).status_code == 404
        planted = [p for p in cfg.simulation.problems if p.kind == "repeat_drop"]
        refreshed = api.post("/growth/signals/refresh", headers=hq)
        assert refreshed.status_code == 200
        assert len(refreshed.json()) == len(planted)
        assert [x["id"] for x in api.get("/growth/signals", headers=hq).json()] == [
            x["id"] for x in refreshed.json()
        ]
    finally:
        api.app.dependency_overrides.pop(get_clock, None)


def test_growth_api_end_to_end(api, app_engine, gt):
    cfg, tid, as_of = gt
    if not cfg.feature_flags.get("growth"):
        pytest.skip("growth is off for this tenant")
    staff = [u for u in cfg.users if u.role != "customer"]
    ctxs = {u.email: ctx_of(app_engine, tid, u.email) for u in staff}
    headers = {u.email: login(api, cfg.slug, u.email) for u in staff}
    api.app.dependency_overrides[get_clock] = lambda: as_of  # after login: tokens use real time
    try:
        hq = next(e for e, c in ctxs.items() if c.role == "hq_owner")
        signals = api.post("/growth/signals/refresh", headers=headers[hq]).json()
        assert signals
        sid, loc = signals[0]["id"], uuid.UUID(signals[0]["location_id"])
        other = next(
            (e for e, c in ctxs.items() if c.role != "hq_owner" and c.can_see_location(loc)), None
        )
        outsider = next(
            (e for e, c in ctxs.items() if c.role != "hq_owner" and not c.can_see_location(loc)),
            None,
        )
        if other is None:
            pytest.skip("no second approver for this location")
        made = api.post(f"/growth/signals/{sid}/campaign", json={}, headers=headers[hq])
        if made.status_code == 422:
            pytest.skip("history too small for an audience at this scale")
        assert made.status_code == 201, made.text
        cid = made.json()["id"]
        approve = f"/growth/campaigns/{cid}/approve"
        yes = {"decision": "approved"}
        if outsider:  # out of scope looks like absent
            assert api.get(f"/growth/campaigns/{cid}", headers=headers[outsider]).status_code == 404
            assert api.post(approve, json=yes, headers=headers[outsider]).status_code == 404
        first = api.post(approve, json=yes, headers=headers[hq])
        assert first.status_code == 200 and first.json()["fully_approved"] is False
        assert outbox(tid) == []
        assert api.post(approve, json=yes, headers=headers[hq]).status_code == 409
        second = api.post(approve, json=yes, headers=headers[other])
        assert second.status_code == 200 and second.json()["fully_approved"] is True
        done = api.get(f"/growth/campaigns/{cid}", headers=headers[hq]).json()
        assert done["status"] == "sent"  # the background send ran after the approval committed
        assert len(outbox(tid)) == done["treatment_n"]
        early = api.post(f"/growth/campaigns/{cid}/verdict", headers=headers[hq])
        assert early.status_code == 409  # window still open
        sent_at = datetime.fromisoformat(done["sent_at"])
        api.app.dependency_overrides[get_clock] = lambda: sent_at + timedelta(days=15)
        final = api.post(f"/growth/campaigns/{cid}/verdict", headers=headers[hq])
        assert final.status_code == 200
        assert final.json()["playbook"]["verdict"] in {"worked", "did_not_work", "inconclusive"}
    finally:
        api.app.dependency_overrides.pop(get_clock, None)


# -- hardening: locking, consent at send time, resumable sends ---------------------------------


def approved_campaign(engine, cfg, tid, as_of, approve_both=True):
    """(campaign_id, hq, other) with a proposal; both approvals recorded if approve_both."""
    signal_id = make_signal(engine, tid, as_of)
    with tenant_session(tid, engine) as s:
        loc = s.get(Signal, signal_id).location_id
    hq, other = approvers(engine, cfg, tid, loc)
    try:
        cid, _ = propose_for(engine, tid, signal_id, hq)
    except ProposalError:
        pytest.skip("history too small for an audience at this scale")
    decide_as(engine, tid, hq, cid)
    if approve_both:
        decide_as(engine, tid, other, cid)
    return cid, hq, other


def test_decision_waits_for_the_campaign_lock_and_sees_a_rejection(app_engine, gt):
    """A decision re-reads the status under a row lock, so an approval racing a rejection can't
    both pass the pending check: a rejected campaign is never approved, hence never sent."""
    cfg, tid, as_of = gt
    cid, hq, other = approved_campaign(app_engine, cfg, tid, as_of, approve_both=False)
    holding, release, outcome = threading.Event(), threading.Event(), []

    def rejecter():  # another request that has locked the campaign and is rejecting it
        with tenant_session(tid, app_engine) as s:
            s.execute(select(Campaign).where(Campaign.id == cid).with_for_update()).one()
            holding.set()
            release.wait(10)
            s.execute(update(Campaign).where(Campaign.id == cid).values(status="rejected"))

    def approver():
        try:
            decide_as(app_engine, tid, other, cid)
            outcome.append("approved")
        except camp.AlreadyDecided:
            outcome.append("refused")

    t1 = threading.Thread(target=rejecter)
    t1.start()
    assert holding.wait(10)
    t2 = threading.Thread(target=approver)
    t2.start()
    t2.join(1.5)
    assert t2.is_alive()  # blocked on the lock, not racing past the status check
    release.set()
    t1.join()
    t2.join()
    assert outcome == ["refused"]
    assert execute_campaign(app_engine, tid, cid).outcome == "refused"
    assert outbox(tid) == []


def test_consent_withdrawn_after_approval_is_not_messaged(app_engine, maint_engine, gt):
    cfg, tid, as_of = gt
    cid, _, _ = approved_campaign(app_engine, cfg, tid, as_of)
    with tenant_session(tid, app_engine) as s:
        members = [m for m in camp.members_of(s, s.get(Campaign, cid)) if m.arm == "treatment"]
        withdrawn = members[0].customer_id
        phones = {i: p for i, p in s.execute(select(Customer.id, Customer.phone))}
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            update(Consent)
            .where(Consent.customer_id == withdrawn, Consent.purpose == "marketing")
            .values(granted=False)
        )
    run = execute_campaign(app_engine, tid, cid)
    assert run.failed == 1 and run.outstanding == 0
    sent_to = [r.to for r in outbox(tid)]
    assert phones[withdrawn] not in sent_to
    assert len(sent_to) == len(members) - 1
    with tenant_session(tid, app_engine) as s:
        status = s.scalar(
            select(CampaignMember.send_status).where(CampaignMember.customer_id == withdrawn)
        )
    assert status == "failed"


def test_a_provider_error_marks_unknown_and_a_later_run_finishes_even_after_expiry(
    app_engine, gt, monkeypatch
):
    cfg, tid, as_of = gt
    cid, _, _ = approved_campaign(app_engine, cfg, tid, as_of)
    with tenant_session(tid, app_engine) as s:
        treated = sum(1 for m in camp.members_of(s, s.get(Campaign, cid)) if m.arm == "treatment")
    mock = get_mock("messaging")
    real_send, calls = mock.send, []

    def flaky(merchant_id, key, request):
        calls.append(key)
        if len(calls) == 1:
            raise RuntimeError("provider blew up")
        return real_send(merchant_id, key, request)

    monkeypatch.setattr(mock, "send", flaky)
    first = execute_campaign(app_engine, tid, cid)  # the error doesn't stop the others
    assert first.outcome == "in_progress" and first.outstanding == 1
    assert len(outbox(tid)) == treated - 1
    monkeypatch.setattr(mock, "send", real_send)
    # Long after the proposal and approvals expired: an `executing` campaign still finishes,
    # with the same key for the member that was unknown.
    later = execute_campaign(app_engine, tid, cid, now=datetime.now(UTC) + timedelta(days=10))
    assert later.outcome == "sent" and later.outstanding == 0
    assert len(outbox(tid)) == treated and len({r.to for r in outbox(tid)}) == treated


def test_expired_approvals_cannot_be_renewed_by_the_same_approver(app_engine, gt):
    """Intended: an approver's decision is final (one row per user). Once it has expired the
    proposer re-proposes rather than the approver approving again."""
    cfg, tid, as_of = gt
    cid, hq, _ = approved_campaign(app_engine, cfg, tid, as_of, approve_both=False)
    with pytest.raises(camp.AlreadyDecided):
        decide_as(app_engine, tid, hq, cid, now=datetime.now(UTC) + timedelta(hours=30))
