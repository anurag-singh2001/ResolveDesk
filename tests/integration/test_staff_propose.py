"""S7.5: staff set a category and propose a remedy on a case that needs a person, for every
tenant (never naming one). The proposal must take the SAME path as an engine one: code checks,
hash-bound approval, executor, verifier. Rule limits come from the vertical pack and settings.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    LineItem,
    Location,
    Payment,
    RefundOperation,
    Ticket,
    Transaction,
    User,
)
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import tenant_id_for
from app.engine.eligibility import CAPTURED_STATUSES
from mocks.registry import get_mock, merchant_id_for, reset_mocks
from tests.helpers import login


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


@pytest.fixture
def world(api, app_engine, maint_engine, seeded_history, tenant):
    """An escalated, uncategorised case on a paid order at an outlet that has a manager, with
    one unit of the dearest line marked missing; logins for the manager, HQ, a customer and
    staff from another outlet / another tenant."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    manager = next(u for u in cfg.users if u.role == "location_manager")
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    with tenant_session(tid, app_engine) as s:
        slugs = {slug: lid for lid, slug in s.execute(select(Location.id, Location.slug)).all()}
        mine = [slugs[x] for x in manager.locations]
        order = s.scalars(
            select(Transaction)
            .join(Payment, Payment.transaction_id == Transaction.id)
            .where(
                Transaction.location_id.in_(mine),
                Transaction.total_paise >= 5000,
                Payment.status.in_(CAPTURED_STATUSES),
            )
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
        line = s.scalars(
            select(LineItem)
            .where(LineItem.transaction_id == order.id)
            .order_by(LineItem.unit_price_paise.desc())
            .limit(1)
        ).one()
        order_id, customer_id, total = order.id, order.customer_id, order.total_paise
        line_id, qty, unit = line.id, line.quantity, line.unit_price_paise
        user_ids = {e: i for i, e in s.execute(select(User.id, User.email)).all()}
        categories = tenant_pack(s).remedies
        pack = tenant_pack(s)
        refund_cat = next(c for c, r in categories.items() if r == "refund_missing")
        voucher_cat = next(c for c, r in categories.items() if r == "voucher")
        other_cat = next(c for c in pack.issue_categories if c not in categories)
        s.execute(update(LineItem).where(LineItem.id == line_id).values(quantity_fulfilled=qty - 1))
    case_id = uuid.uuid4()
    with tenant_session(tid, app_engine) as s:
        s.add(
            Case(
                id=case_id,
                tenant_id=tid,
                customer_id=customer_id,
                transaction_id=order_id,
                status="escalated",
                channel="app",
                opened_at=datetime.now(UTC),
            )
        )
    foreign = next(c for c in seeded_history.values() if c.slug != cfg.slug)
    other_outlet = next(
        (
            u
            for u in cfg.users
            if u.role == "location_manager" and not set(u.locations) & set(manager.locations)
        ),
        None,
    )
    w = {
        "tid": tid,
        "engine": app_engine,
        "case": case_id,
        "order": order_id,
        "total": total,
        "unit": unit,
        "refund_cat": refund_cat,
        "voucher_cat": voucher_cat,
        "other_cat": other_cat,
        "manager_id": user_ids[manager.email],
        "mgr": login(api, cfg.slug, manager.email),
        "hq": login(api, cfg.slug, hq.email),
        "customer": login(api, cfg.slug, next(u.email for u in cfg.users if u.role == "customer")),
        "foreign": login(
            api, foreign.slug, next(u.email for u in foreign.users if u.role == "hq_owner")
        ),
        "other_outlet": login(api, cfg.slug, other_outlet.email) if other_outlet else None,
        "merchant": merchant_id_for(tid),
    }
    yield w
    with tenant_session(tid, app_engine) as s:
        s.execute(update(LineItem).where(LineItem.id == line_id).values(quantity_fulfilled=qty))
    with tenant_session(tid, maint_engine) as s:
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id == case_id))
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid, RefundOperation.transaction_id == order_id
            )
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id == case_id))


def _proposals(w) -> list[ActionProposal]:
    with tenant_session(w["tid"], w["engine"]) as s:
        rows = s.scalars(select(ActionProposal).where(ActionProposal.case_id == w["case"])).all()
        s.expunge_all()
        return list(rows)


def _set_status(w, status):
    with tenant_session(w["tid"], w["engine"]) as s:
        s.execute(update(Case).where(Case.id == w["case"]).values(status=status))


def _url(w, tail):
    return f"/cases/{w['case']}/{tail}"


def _categorise(api, w, category, who="mgr"):
    return api.post(_url(w, "categorise"), headers=w[who], json={"category": category})


def _options(api, w, who="mgr"):
    return api.get(_url(w, "staff-remedy-options"), headers=w[who])


def _propose(api, w, action, amount, who="mgr"):
    return api.post(
        _url(w, "propose"), headers=w[who], json={"action": action, "amount_paise": amount}
    )


def test_uncategorised_case_offers_categories_only(api, world):
    out = _options(api, world).json()
    assert out["category"] is None and out["options"] == [] and out["note"]
    assert world["refund_cat"] in out["categories"]


def test_categorise_is_stored_and_audited(api, world):
    w = world
    resp = _categorise(api, w, w["refund_cat"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == w["refund_cat"]
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.get(Case, w["case"]).category == w["refund_cat"]
        ev = [
            (e.actor_id, e.payload)
            for e in s.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id == w["case"],
                    AuditEvent.event == "case.categorised_by_staff",
                )
            )
        ]
    assert len(ev) == 1 and ev[0][0] == str(w["manager_id"])
    assert ev[0][1]["category"] == w["refund_cat"]
    assert _categorise(api, w, w["refund_cat"]).status_code == 200  # a repeat adds no audit row
    with tenant_session(w["tid"], w["engine"]) as s:
        assert (
            s.scalar(
                select(func.count()).where(
                    AuditEvent.entity_id == w["case"],
                    AuditEvent.event == "case.categorised_by_staff",
                )
            )
            == 1
        )
    assert _categorise(api, w, "not_a_category").status_code == 422


def test_refund_follows_the_same_path_to_one_verified_payout(api, world):
    w = world
    _categorise(api, w, w["refund_cat"])
    opts = _options(api, w).json()["options"]
    refund = next(o for o in opts if o["action"] == "refund")
    assert 1 <= refund["min_paise"] <= refund["max_paise"] <= w["unit"]  # one unit is missing
    amount = refund["max_paise"]

    first = _propose(api, w, "refund", amount)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["status"] == "awaiting_approval" and body["created"] is True
    assert body["amount_paise"] == amount
    again = _propose(api, w, "refund", amount)  # a double click: same proposal
    assert again.status_code == 200 and again.json()["proposal_id"] == body["proposal_id"]
    assert again.json()["created"] is False

    [proposal] = _proposals(w)
    assert proposal.proposed_by == w["manager_id"] and proposal.amount_paise == amount
    assert proposal.params["amount_paise"] == amount and "reason" in proposal.params
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.get(Case, w["case"]).status == "awaiting_approval"
        events = s.scalars(select(AuditEvent.event).where(AuditEvent.entity_id == w["case"])).all()
    assert events.count("case.proposed_by_staff") == 1

    queue = api.get("/approvals", headers=w["hq"]).json()
    item = next(p for p in queue if p["case_id"] == str(w["case"]))
    assert item["eligible"] and item["amount_paise"] == amount
    decided = api.post(
        f"/approvals/{item['proposal_id']}/decision", headers=w["hq"], json={"decision": "approved"}
    )
    assert decided.status_code == 200, decided.text
    with tenant_session(w["tid"], w["engine"]) as s:
        approval = s.scalar(select(Approval).where(Approval.proposal_id == proposal.id))
        assert approval.payload_hash == proposal.payload_hash  # bound to what was proposed
        assert s.get(Case, w["case"]).status == "resolved"
    ops = get_mock("payment").operations(w["merchant"])
    assert len(ops) == 1
    # Once the case moved on, the same request is still the same proposal, never a second payout.
    replay = _propose(api, w, "refund", amount)
    assert replay.status_code == 200 and replay.json()["proposal_id"] == body["proposal_id"]
    assert len(get_mock("payment").operations(w["merchant"])) == 1


def test_out_of_rule_choices_are_rejected_with_a_reason_and_store_nothing(api, world):
    w = world
    assert _propose(api, w, "refund", 100).status_code == 422  # no category yet
    _categorise(api, w, w["refund_cat"])
    top = next(o for o in _options(api, w).json()["options"] if o["action"] == "refund")
    over = _propose(api, w, "refund", top["max_paise"] + 1)
    assert over.status_code == 422 and "between" in over.json()["detail"]
    assert _propose(api, w, "refund", 0).status_code == 422
    assert _propose(api, w, "refund", -500).status_code == 422
    assert _propose(api, w, "refund", None).status_code == 422
    assert _propose(api, w, "refund", 12.5).status_code == 422  # money is integer paise
    assert _propose(api, w, "refund", "100").status_code == 422
    assert _propose(api, w, "refund", True).status_code == 422
    wrong = _propose(api, w, "free_item_voucher", 1000)  # the category's rule is a refund
    assert wrong.status_code == 422 and "not allowed" in wrong.json()["detail"]
    assert _propose(api, w, "send_status_update", 100).status_code == 422
    assert _propose(api, w, "no_such_action", 100).status_code == 422
    assert _proposals(w) == []
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.get(Case, w["case"]).status == "escalated"


def test_a_category_without_a_remedy_offers_none(api, world):
    w = world
    _categorise(api, w, w["other_cat"])
    out = _options(api, w).json()
    assert out["options"] == [] and out["note"]
    assert _propose(api, w, "refund", 100).status_code == 422
    assert _proposals(w) == []


def test_voucher_is_sized_to_the_order_and_goes_through_the_same_checks(api, world):
    w = world
    _categorise(api, w, w["voucher_cat"])
    options = _options(api, w).json()["options"]
    voucher = next(o for o in options if o["action"] == "free_item_voucher")
    assert 0 < voucher["min_paise"] <= voucher["max_paise"] <= w["total"]
    assert voucher["max_paise"] % 100 == 0
    over = _propose(api, w, "free_item_voucher", voucher["max_paise"] + 100)
    assert over.status_code == 422
    assert _propose(api, w, "free_item_voucher", w["total"] + 100).status_code == 422
    ok = _propose(api, w, "free_item_voucher", voucher["min_paise"])
    assert ok.status_code == 201, ok.text
    [proposal] = _proposals(w)
    assert proposal.action == "free_item_voucher" and proposal.proposed_by == w["manager_id"]
    assert proposal.amount_paise == voucher["min_paise"] <= w["total"]
    # Even under the auto-approve cap a person-made proposal waits for another person.
    assert ok.json()["status"] == "awaiting_approval"
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == proposal.id)) is None
        assert s.get(Case, w["case"]).status == "awaiting_approval"


def test_two_simultaneous_identical_requests_make_one_proposal(api, world):
    w = world
    _categorise(api, w, w["refund_cat"])
    amount = next(o for o in _options(api, w).json()["options"] if o["action"] == "refund")[
        "min_paise"
    ]
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda _: _propose(api, w, "refund", amount).status_code, range(2)))
    assert sorted(codes) == [200, 201]
    assert len(_proposals(w)) == 1


def test_who_may_use_it(api, world):
    w = world
    calls = (
        lambda who: _options(api, w, who),
        lambda who: _categorise(api, w, w["refund_cat"], who),
        lambda who: _propose(api, w, "refund", 100, who),
    )
    for call in calls:
        assert call("customer").status_code == 403
        assert call("foreign").status_code == 404  # another tenant's case does not exist
        if w["other_outlet"] is not None:
            assert call("other_outlet").status_code == 404  # an outlet outside the caller's scope
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.get(Case, w["case"]).category is None
    assert _proposals(w) == []


@pytest.mark.parametrize("status", ["investigating", "awaiting_approval", "executing", "closed"])
def test_a_case_that_does_not_need_a_person_is_409(api, world, status):
    w = world
    _categorise(api, w, w["refund_cat"])
    amount = next(o for o in _options(api, w).json()["options"] if o["action"] == "refund")[
        "min_paise"
    ]
    _set_status(w, status)
    assert _options(api, w).status_code == 409
    assert _categorise(api, w, w["voucher_cat"]).status_code == 409
    assert _propose(api, w, "refund", amount).status_code == 409
    assert _proposals(w) == []


def test_a_case_with_an_approved_payout_is_not_proposed_again(api, world):
    w = world
    _categorise(api, w, w["refund_cat"])
    top = next(o for o in _options(api, w).json()["options"] if o["action"] == "refund")
    assert _propose(api, w, "refund", top["min_paise"]).status_code == 201
    [proposal] = _proposals(w)
    with tenant_session(w["tid"], w["engine"]) as s:
        s.add(
            Approval(
                id=uuid.uuid4(),
                tenant_id=w["tid"],
                proposal_id=proposal.id,
                payload_hash=proposal.payload_hash,
                decision="approved",
                mode="human",
                decided_by=w["manager_id"],
                decided_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        s.execute(update(Case).where(Case.id == w["case"]).values(status="escalated"))
    assert _propose(api, w, "refund", top["max_paise"]).status_code == 409
    assert len(_proposals(w)) == 1


def _decide(api, w, who, pid, decision="approved"):
    return api.post(f"/approvals/{pid}/decision", headers=w[who], json={"decision": decision})


def test_the_proposer_cannot_approve_but_can_withdraw(api, world):
    w = world
    _categorise(api, w, w["refund_cat"])
    low = next(o for o in _options(api, w).json()["options"] if o["action"] == "refund")[
        "min_paise"
    ]
    pid = _propose(api, w, "refund", low).json()["proposal_id"]
    assert _decide(api, w, "mgr", pid).status_code == 403  # four eyes, whatever the amount
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == uuid.UUID(pid))) is None
    shown = next(
        p for p in api.get("/approvals", headers=w["hq"]).json() if p["proposal_id"] == pid
    )
    assert shown["proposed_by_name"]
    assert _decide(api, w, "mgr", pid, "rejected").status_code == 200  # withdrawing is allowed


def test_another_approver_in_scope_can_approve_a_staff_proposal(api, world):
    w = world
    _categorise(api, w, w["voucher_cat"])
    low = _options(api, w).json()["options"][0]["min_paise"]
    action = _options(api, w).json()["options"][0]["action"]
    pid = _propose(api, w, action, low).json()["proposal_id"]
    assert _decide(api, w, "hq", pid).status_code == 200


def test_a_replay_reports_the_real_state(api, world):
    w = world
    _categorise(api, w, w["voucher_cat"])
    opt = _options(api, w).json()["options"][0]
    first = _propose(api, w, opt["action"], opt["min_paise"]).json()
    assert _decide(api, w, "hq", first["proposal_id"], "rejected").status_code == 200
    again = _propose(api, w, opt["action"], opt["min_paise"])
    assert again.status_code == 200 and again.json()["status"] == "rejected"


def test_after_a_switch_the_same_payload_is_a_new_proposal(api, world):
    w = world
    _categorise(api, w, w["refund_cat"])
    refund = next(o for o in _options(api, w).json()["options"] if o["action"] == "refund")
    old = _propose(api, w, "refund", refund["min_paise"]).json()["proposal_id"]
    voucher_opts = [o for o in _options_for(api, w, old) if o["action"] != "refund"]
    if not voucher_opts:  # a pack whose rule has only refunds: nothing to switch to
        pytest.skip("no other remedy to switch to")
    alt = voucher_opts[0]
    sw = api.post(
        f"/approvals/{old}/switch",
        headers=w["hq"],
        json={"action": alt["action"], "amount_paise": alt["min_paise"], "note": "test"},
    )
    assert sw.status_code == 200, sw.text
    _set_status(w, "escalated")  # the case needs a person again
    again = _propose(api, w, "refund", refund["min_paise"])
    assert again.status_code == 201 and again.json()["proposal_id"] != old


def _options_for(api, w, pid):
    resp = api.get(f"/approvals/{pid}/alternatives", headers=w["hq"])
    assert resp.status_code == 200, resp.text
    return resp.json()["alternatives"]
