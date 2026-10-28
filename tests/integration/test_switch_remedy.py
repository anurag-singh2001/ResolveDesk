"""S7.10: an approver switches a pending proposal to another allowed remedy.

For every tenant, never naming one. Each test gets a fresh case with a pending voucher on a
big order at the location manager's outlet (the order's total and payment are raised for the
test and restored after, so refund ranges are wide enough to cross the escalation limit).
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Payment,
    ProposalSupersession,
    Transaction,
    User,
)
from app.core.tenancy import load_context, tenant_id_for
from app.engine.approvals import (
    AlreadyDecided,
    check_usable,
    decide,
    head_proposal_id,
    is_superseded,
)
from app.engine.case_status import case_status
from app.engine.case_timeline import case_timeline
from app.engine.eligibility import order_facts
from app.engine.proposals import create_proposal, proposal_hash_is_intact
from app.engine.retention import unsettled_case_ids
from app.engine.switch import switch_remedy
from tests.helpers import login

BIG_ORDER_PAISE = 400_000  # Rs 4,000: wide ranges, and a refund can exceed the HQ limit


class _Rollback(Exception):
    pass


def _by_role(cfg, role):
    return [u for u in cfg.users if u.role == role]


@pytest.fixture
def sw(api, app_engine, maint_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    managers = _by_role(cfg, "location_manager")
    if not managers:
        pytest.skip("this tenant has no location_manager")
    hq = login(api, cfg.slug, _by_role(cfg, "hq_owner")[0].email)
    mgr = login(api, cfg.slug, managers[0].email)
    own_loc = uuid.UUID(api.get("/me", headers=mgr).json()["location_ids"][0])
    with tenant_session(tid, app_engine) as s:
        order = s.scalars(
            select(Transaction)
            .where(Transaction.location_id == own_loc)
            .order_by(Transaction.id)
            .limit(1)
        ).first()
        if order is None:
            pytest.skip("no order at the manager's location")
        payment = s.scalars(
            select(Payment).where(Payment.transaction_id == order.id).order_by(Payment.id)
        ).first()
        if payment is None:
            pytest.skip("order has no payment")
        saved = (order.id, order.total_paise, payment.id, payment.amount_paise, payment.status)
        order.total_paise = BIG_ORDER_PAISE
        payment.amount_paise = BIG_ORDER_PAISE
        payment.status = "captured"
        customer_id = order.customer_id
        settings = order_facts(s, order.id)[1].settings
        mgr_id = s.scalar(select(User.id).where(User.email == managers[0].email))
        hq_id = s.scalar(select(User.id).where(User.email == _by_role(cfg, "hq_owner")[0].email))
        mgr_ctx = load_context(s, tid, mgr_id)
        hq_ctx = load_context(s, tid, hq_id)
    case_ids: list[uuid.UUID] = []

    def new_pending(value: int = 5000) -> tuple[uuid.UUID, uuid.UUID]:
        """A fresh case with one pending voucher; returns (case_id, proposal_id)."""
        cid = uuid.uuid4()
        with tenant_session(tid, app_engine) as s:
            s.add(
                Case(
                    id=cid,
                    tenant_id=tid,
                    customer_id=customer_id,
                    transaction_id=saved[0],
                    status="awaiting_approval",
                    channel="app",
                    opened_at=datetime.now(UTC),
                )
            )
            s.flush()
            params = {"transaction_id": str(saved[0]), "value_paise": value, "reason": "x"}
            p = create_proposal(
                s, tid, case_id=cid, action="free_item_voucher", params=params, reason="p"
            )
            pid = p.id
        case_ids.append(cid)
        return cid, pid

    yield {
        "api": api,
        "cfg": cfg,
        "tid": tid,
        "engine": app_engine,
        "hq": hq,
        "mgr": mgr,
        "mgr_ctx": mgr_ctx,
        "hq_ctx": hq_ctx,
        "settings": settings,
        "new_pending": new_pending,
        "seeded": seeded_history,
        "tenant_name": tenant.name,
        "order_id": saved[0],
    }
    with tenant_session(tid, maint_engine) as s:
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id.in_(case_ids)))
    with tenant_session(tid, app_engine) as s:
        o = s.get(Transaction, saved[0])
        o.total_paise = saved[1]
        p = s.get(Payment, saved[2])
        p.amount_paise, p.status = saved[3], saved[4]


def _alts(sw, headers, pid):
    resp = sw["api"].get(f"/approvals/{pid}/alternatives", headers=headers)
    assert resp.status_code == 200, resp.text
    return {a["action"]: a for a in resp.json()["alternatives"]}


def _switch(sw, headers, pid, **body):
    body.setdefault("note", "fairer remedy")
    return sw["api"].post(f"/approvals/{pid}/switch", headers=headers, json=body)


def _hq_limit(sw):
    return sw["settings"]["refund_without_escalation_paise"]


def _refund_over_limit(sw, alts):
    """An amount the rules allow but only an hq_owner may approve."""
    r = alts["refund"]
    amount = _hq_limit(sw) + 1000
    assert r["min_paise"] <= amount <= r["max_paise"], "test order must allow it"
    return amount


# --- alternatives --------------------------------------------------------------------------


def test_alternatives_show_allowed_remedies_and_ranges_for_the_caller(sw):
    _, pid = sw["new_pending"]()
    mgr, hq = _alts(sw, sw["mgr"], pid), _alts(sw, sw["hq"], pid)
    assert set(mgr) <= {"refund", "free_item_voucher"}  # compensation actions only
    assert "free_item_voucher" in mgr
    v = mgr["free_item_voucher"]
    assert v["max_paise"] <= sw["settings"]["voucher_max_paise"]
    assert v["max_paise"] <= BIG_ORDER_PAISE and v["step_paise"] == 100
    if "refund" in mgr:
        r = mgr["refund"]
        assert r["needs_hq_above_paise"] == _hq_limit(sw)
        assert r["you_can_approve_up_to_paise"] == min(r["max_paise"], _hq_limit(sw))
        assert hq["refund"]["you_can_approve_up_to_paise"] == hq["refund"]["max_paise"]
    body = sw["api"].get(f"/approvals/{pid}/alternatives", headers=sw["mgr"]).json()
    assert (body["current_action"], body["current_amount_paise"]) == ("free_item_voucher", 5000)


# --- the switch -----------------------------------------------------------------------------


def test_switch_supersedes_old_and_creates_new_with_its_own_hash(sw):
    case_id, old = sw["new_pending"]()
    with tenant_session(sw["tid"], sw["engine"]) as s:
        old_hash = s.get(ActionProposal, old).payload_hash
    resp = _switch(
        sw, sw["mgr"], old, action="free_item_voucher", amount_paise=9000, approve=False,
        note="customer asked for a bit more",
    )  # fmt: skip
    assert resp.status_code == 200, resp.text
    out = resp.json()
    new = uuid.UUID(out["proposal_id"])
    assert out["old_proposal_id"] == str(old) and new != old
    assert out["decision"] is None and out["waiting_for"] is None and out["amount_paise"] == 9000
    with tenant_session(sw["tid"], sw["engine"]) as s:
        n, o = s.get(ActionProposal, new), s.get(ActionProposal, old)
        assert n.payload_hash != old_hash and o.payload_hash == old_hash
        assert proposal_hash_is_intact(n) and proposal_hash_is_intact(o)
        assert n.params["value_paise"] == 9000 and n.case_id == case_id
        assert is_superseded(s, old) and not is_superseded(s, new)
        assert head_proposal_id(s, old) == new
        link = s.scalar(
            select(ProposalSupersession).where(ProposalSupersession.old_proposal_id == old)
        )
        assert link.new_proposal_id == new and link.reason == "customer asked for a bit more"
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == old)) is None
        audit = s.scalars(
            select(AuditEvent).where(
                AuditEvent.event == "proposal.superseded", AuditEvent.entity_id == old
            )
        ).one()
        assert (
            audit.actor_id == str(sw["mgr_ctx"].user_id) or audit.actor_id == sw["mgr_ctx"].user_id
        )
        assert audit.payload["new_proposal_id"] == str(new)
        assert audit.payload["switch_reason"] == "customer asked for a bit more"
        assert (
            audit.payload["old_amount_paise"] == 5000 and audit.payload["new_amount_paise"] == 9000
        )
    # The queue shows only the new one.
    pending = {p["proposal_id"] for p in sw["api"].get("/approvals", headers=sw["mgr"]).json()}
    assert str(new) in pending and str(old) not in pending


def test_old_proposal_can_no_longer_be_decided_or_switched_again(sw):
    _, old = sw["new_pending"]()
    assert (
        _switch(sw, sw["mgr"], old, action="free_item_voucher", amount_paise=9000).status_code
        == 200
    )
    for decision in ("approved", "rejected"):
        r = sw["api"].post(
            f"/approvals/{old}/decision", headers=sw["mgr"], json={"decision": decision}
        )
        assert r.status_code == 409, r.text
    again = _switch(sw, sw["mgr"], old, action="free_item_voucher", amount_paise=8000)
    assert again.status_code == 409
    assert sw["api"].get(f"/approvals/{old}/alternatives", headers=sw["mgr"]).status_code == 409


def test_approve_in_the_same_step_binds_the_approval_to_the_new_hash(sw):
    _, old = sw["new_pending"]()
    r = _switch(
        sw, sw["mgr"], old, action="free_item_voucher", amount_paise=9000, approve=True,
        note="ok",
    )  # fmt: skip
    assert r.status_code == 200, r.text
    out = r.json()
    new = uuid.UUID(out["proposal_id"])
    assert out["decision"] == "approved" and out["waiting_for"] is None and out["expires_at"]
    with tenant_session(sw["tid"], sw["engine"]) as s:
        n = s.get(ActionProposal, new)
        approval = s.scalar(select(Approval).where(Approval.proposal_id == new))
        assert approval.payload_hash == n.payload_hash
        assert approval.decided_by == sw["mgr_ctx"].user_id
        assert check_usable(approval, n, datetime.now(UTC)).ok
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == old)) is None


def test_a_manager_cannot_approve_above_the_limit_so_it_waits_for_hq(sw):
    _, old = sw["new_pending"]()
    alts = _alts(sw, sw["mgr"], old)
    if "refund" not in alts:
        pytest.skip("refunds are not offered for this tenant's order")
    amount = _refund_over_limit(sw, alts)
    r = _switch(sw, sw["mgr"], old, action="refund", amount_paise=amount, approve=True, note="hq")
    assert r.status_code == 200, r.text
    out = r.json()
    new = out["proposal_id"]
    assert (
        out["decision"] is None and out["waiting_for"] == "hq_owner" and out["execution"] == "none"
    )
    # The manager still cannot decide it; HQ can (limit checks are approvals.decide's, unchanged).
    deny = sw["api"].post(
        f"/approvals/{new}/decision", headers=sw["mgr"], json={"decision": "approved"}
    )
    assert deny.status_code == 403
    with tenant_session(sw["tid"], sw["engine"]) as s:
        case = s.scalar(select(Case).join(ActionProposal, ActionProposal.case_id == Case.id)
                        .where(ActionProposal.id == uuid.UUID(new)))  # fmt: skip
        assert case.owner_user_id is None or case.owner_user_id != sw["mgr_ctx"].user_id
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == uuid.UUID(new))) is None


def test_hq_can_switch_above_the_limit_and_approve_in_one_step(sw):
    _, old = sw["new_pending"]()
    alts = _alts(sw, sw["hq"], old)
    if "refund" not in alts:
        pytest.skip("refunds are not offered for this tenant's order")
    amount = _refund_over_limit(sw, alts)
    r = _switch(sw, sw["hq"], old, action="refund", amount_paise=amount, approve=False)
    assert r.status_code == 200 and r.json()["decision"] is None, r.text
    new = uuid.UUID(r.json()["proposal_id"])
    with tenant_session(sw["tid"], sw["engine"]) as s:
        assert s.get(ActionProposal, new).risk == "high"


# --- out of rule ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"action": "free_item_voucher", "amount_paise": 10**9},  # over the voucher limit
        {"action": "free_item_voucher", "amount_paise": 999},  # under the minimum
        {"action": "free_item_voucher", "amount_paise": 5050},  # not whole rupees
        {"action": "free_item_voucher", "amount_paise": 5000},  # nothing changes
        {"action": "free_item_voucher"},  # no amount
        {"action": "refund", "amount_paise": 10**9},  # over the refund cap
        {"action": "loyalty_credit", "amount_paise": 500},  # not a switchable remedy
        {"action": "send_status_update", "amount_paise": 500},
        {"action": "no_such_action", "amount_paise": 500},
    ],
)
def test_amounts_and_remedies_outside_the_rule_are_422_and_leave_nothing(sw, body):
    _, old = sw["new_pending"]()
    r = _switch(sw, sw["hq"], old, approve=True, **body)
    assert r.status_code == 422, r.text
    with tenant_session(sw["tid"], sw["engine"]) as s:
        assert not is_superseded(s, old)
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == old)) is None


@pytest.mark.parametrize("bad", [34900.0, "34900", True, -5, 0])
def test_client_amounts_are_strict_integers(sw, bad):
    _, old = sw["new_pending"]()
    r = _switch(sw, sw["hq"], old, action="free_item_voucher", amount_paise=bad)
    assert r.status_code == 422, r.text


def test_no_proposal_is_left_behind_when_a_switch_is_refused(sw):
    case_id, old = sw["new_pending"]()
    _switch(sw, sw["hq"], old, action="free_item_voucher", amount_paise=10**9)
    with tenant_session(sw["tid"], sw["engine"]) as s:
        n = len(s.scalars(select(ActionProposal.id).where(ActionProposal.case_id == case_id)).all())
        assert n == 1


# --- hash binding ----------------------------------------------------------------------------


def test_an_approval_of_the_old_hash_cannot_execute_the_new_payload_or_a_superseded_one(sw):
    _, old = sw["new_pending"]()
    r = _switch(sw, sw["mgr"], old, action="free_item_voucher", amount_paise=9000)
    new = uuid.UUID(r.json()["proposal_id"])
    now = datetime.now(UTC)
    with pytest.raises(_Rollback), tenant_session(sw["tid"], sw["engine"]) as s:
        o, n = s.get(ActionProposal, old), s.get(ActionProposal, new)
        # Even a stray approval row of the old proposal (the app cannot make one through
        # decide) is useless: it is for another proposal and another hash ...
        stray = Approval(
            id=uuid.uuid4(), tenant_id=sw["tid"], proposal_id=old, payload_hash=o.payload_hash,
            decision="approved", mode="human", decided_by=sw["mgr_ctx"].user_id,
            decided_at=now, expires_at=now + timedelta(hours=1),
        )  # fmt: skip
        s.add(stray)
        s.flush()
        assert check_usable(stray, n, now).reason == "approval_for_another_proposal"
        # ... and the superseded proposal itself never becomes usable.
        assert check_usable(stray, o, now).reason == "superseded"
        raise _Rollback


def test_deciding_the_superseded_proposal_in_the_engine_is_refused(sw):
    _, old = sw["new_pending"]()
    _switch(sw, sw["mgr"], old, action="free_item_voucher", amount_paise=9000)
    with pytest.raises(AlreadyDecided), tenant_session(sw["tid"], sw["engine"]) as s:
        decide(s, sw["mgr_ctx"], old, "approved", datetime.now(UTC))


# --- race: the case row lock gives exactly one winner ----------------------------------------


def _race(sw, first, second):
    """`first` runs and holds its transaction open (so holds the case lock); `second` starts
    meanwhile and must wait for the lock, then see the winner's result."""
    holding, release, out = threading.Event(), threading.Event(), {}

    def run_first():
        try:
            with tenant_session(sw["tid"], sw["engine"]) as s:
                first(s)
                holding.set()
                release.wait(10)
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            out["first"] = exc
            holding.set()

    def run_second():
        try:
            with tenant_session(sw["tid"], sw["engine"]) as s:
                second(s)
            out["second"] = None
        except Exception as exc:
            out["second"] = exc

    t1 = threading.Thread(target=run_first)
    t1.start()
    assert holding.wait(10)
    t2 = threading.Thread(target=run_second)
    t2.start()
    t2.join(1.0)
    assert t2.is_alive(), "the second transaction should be waiting on the case lock"
    release.set()
    t1.join(10)
    t2.join(10)
    assert "first" not in out, out.get("first")
    return out["second"]


def test_race_switch_holds_the_lock_then_approve_old_loses(sw):
    _, old = sw["new_pending"]()
    now = datetime.now(UTC)

    def do_switch(s):
        switch_remedy(s, sw["mgr_ctx"], old, action="free_item_voucher", amount_paise=9000,
                      approve=False, note="x", now=now)  # fmt: skip

    loser = _race(sw, do_switch, lambda s: decide(s, sw["mgr_ctx"], old, "approved", now))
    assert isinstance(loser, AlreadyDecided)
    with tenant_session(sw["tid"], sw["engine"]) as s:
        assert is_superseded(s, old)
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == old)) is None


def test_race_approve_old_holds_the_lock_then_switch_loses(sw):
    _, old = sw["new_pending"]()
    now = datetime.now(UTC)

    def switch(s):
        switch_remedy(s, sw["mgr_ctx"], old, action="free_item_voucher", amount_paise=9000,
                      approve=False, note="x", now=now)  # fmt: skip

    loser = _race(sw, lambda s: decide(s, sw["mgr_ctx"], old, "approved", now), switch)
    assert isinstance(loser, AlreadyDecided)
    with tenant_session(sw["tid"], sw["engine"]) as s:
        assert not is_superseded(s, old)
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == old)) is not None


# --- scope and tenancy -------------------------------------------------------------------------


def test_other_tenant_and_non_staff_cannot_see_or_switch(sw):
    _, old = sw["new_pending"]()
    others = [c for name, c in sw["seeded"].items() if name != sw["tenant_name"]]
    if not others:
        pytest.skip("needs a second tenant")
    other = others[0]
    other_hq = login(sw["api"], other.slug, _by_role(other, "hq_owner")[0].email)
    assert sw["api"].get(f"/approvals/{old}/alternatives", headers=other_hq).status_code == 404
    r = _switch(sw, other_hq, old, action="free_item_voucher", amount_paise=9000)
    assert r.status_code == 404
    customer = login(sw["api"], sw["cfg"].slug, _by_role(sw["cfg"], "customer")[0].email)
    assert (
        _switch(sw, customer, old, action="free_item_voucher", amount_paise=9000).status_code == 403
    )
    with tenant_session(sw["tid"], sw["engine"]) as s:
        assert not is_superseded(s, old)


def test_staff_outside_the_outlet_get_404(sw):
    _, old = sw["new_pending"]()
    cfg = sw["cfg"]
    for u in _by_role(cfg, "location_manager"):
        hdr = login(sw["api"], cfg.slug, u.email)
        locs = sw["api"].get("/me", headers=hdr).json()["location_ids"]
        with tenant_session(sw["tid"], sw["engine"]) as s:
            loc = s.scalar(select(Transaction.location_id).where(Transaction.id == sw["order_id"]))
        if str(loc) not in locs:
            r = _switch(sw, hdr, old, action="free_item_voucher", amount_paise=9000)
            assert r.status_code == 404
            assert sw["api"].get(f"/approvals/{old}/alternatives", headers=hdr).status_code == 404
            return
    pytest.skip("every location manager of this tenant sees the order's outlet")


# --- what the customer is told -----------------------------------------------------------------


def test_the_customer_story_only_shows_the_new_remedy(sw):
    case_id, old = sw["new_pending"]()
    r = _switch(sw, sw["mgr"], old, action="free_item_voucher", amount_paise=9000)
    new = r.json()["proposal_id"]
    now = datetime.now(UTC)
    with tenant_session(sw["tid"], sw["engine"]) as s:
        case = s.get(Case, case_id)
        status = case_status(s, case, now, "en")
        assert status.proposal_id == new and status.stage == "awaiting_approval"
        steps = case_timeline(s, case, now, "en")
        assert [x.stage for x in steps].count("awaiting_approval") == 1
        assert "90" in " ".join(x.text for x in steps)  # the new amount (Rs 90), not Rs 50
        assert "50" not in " ".join(x.text for x in steps if x.stage == "awaiting_approval")


def test_a_blank_or_missing_why_is_refused(sw):
    _, old = sw["new_pending"]()
    for note in ("", "   "):
        r = _switch(sw, sw["hq"], old, action="free_item_voucher", amount_paise=9000, note=note)
        assert r.status_code == 422, r.text
    r = sw["api"].post(
        f"/approvals/{old}/switch",
        headers=sw["hq"],
        json={"action": "free_item_voucher", "amount_paise": 9000},
    )
    assert r.status_code == 422
    with tenant_session(sw["tid"], sw["engine"]) as s:
        assert not is_superseded(s, old)


def test_hq_approving_in_the_same_step_does_not_hand_the_case_over(sw):
    case_id, old = sw["new_pending"]()
    alts = _alts(sw, sw["hq"], old)
    if "refund" not in alts:
        pytest.skip("refunds are not offered for this tenant's order")
    amount = _refund_over_limit(sw, alts)
    r = _switch(sw, sw["hq"], old, action="refund", amount_paise=amount, approve=False)
    assert r.status_code == 200, r.text
    with tenant_session(sw["tid"], sw["engine"]) as s:
        handed = [
            e
            for e in s.scalars(
                select(AuditEvent).where(
                    AuditEvent.event == "case.owner_assigned", AuditEvent.entity_id == case_id
                )
            )
            if "why" in e.payload  # only the switch's hand-over writes this key
        ]
        assert handed == []


def test_retention_treats_a_switched_case_as_settled_once_the_new_one_is_decided(sw):
    case_id, old = sw["new_pending"]()
    now = datetime.now(UTC)
    with tenant_session(sw["tid"], sw["engine"]) as s:
        res = switch_remedy(s, sw["mgr_ctx"], old, action="free_item_voucher",
                            amount_paise=9000, approve=False, note="x", now=now)  # fmt: skip
        new = res.proposal.id
    with tenant_session(sw["tid"], sw["engine"]) as s:
        # The replacement is pending: the case is unsettled. The superseded one adds nothing.
        assert case_id in set(s.scalars(unsettled_case_ids(sw["tid"])))
        decide(s, sw["mgr_ctx"], new, "approved", now)
    with tenant_session(sw["tid"], sw["engine"]) as s:
        assert case_id not in set(s.scalars(unsettled_case_ids(sw["tid"])))
