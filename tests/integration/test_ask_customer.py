"""S8.10: an approver asks the customer to choose between two remedies, then a person reviews.

For every tenant, never naming one. Each test makes its own case with a pending voucher on one
of a customer's orders (the order's total and payment are set for the test and restored after).
Nothing here approves a real case or touches a payment provider: approvals go through
`decide`, which only records the decision.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Customer,
    Payment,
    ProposalOffer,
    ProposalSupersession,
    TenantSetting,
    Ticket,
    TicketMessage,
    Transaction,
    User,
)
from app.core.tenancy import load_context, tenant_id_for
from app.engine import ask_customer
from app.engine.approvals import AlreadyDecided, WaitingForCustomer, check_usable, decide
from app.engine.eligibility import order_facts
from app.engine.proposals import create_proposal, proposal_hash_is_intact
from tests.helpers import login

RS_149 = 14_900


def _emails(cfg, role):
    return [u.email for u in cfg.users if u.role == role]


@pytest.fixture
def ask(api, app_engine, maint_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    customers = _emails(cfg, "customer")
    if len(customers) < 2:
        pytest.skip("needs two customers")
    hq_email = _emails(cfg, "hq_owner")[0]
    saved: dict[uuid.UUID, tuple] = {}
    made: list[uuid.UUID] = []
    info: dict = {"tid": tid, "api": api, "engine": app_engine, "cfg": cfg}
    orders: dict[str, uuid.UUID] = {}
    cids: dict[str, uuid.UUID] = {}
    with tenant_session(tid, app_engine) as s:
        for label, email in (("me", customers[0]), ("other", customers[1])):
            uid = s.scalar(select(User.id).where(User.email == email))
            cid = s.scalar(select(Customer.id).where(Customer.user_id == uid))
            row = s.execute(
                select(Transaction.id)
                .join(Payment, Payment.transaction_id == Transaction.id)
                .where(Transaction.customer_id == cid)
                .order_by(Transaction.id)
                .limit(1)
            ).first()
            if row is None:
                pytest.skip("customer has no paid order")
            orders[label], cids[label] = row[0], cid
        hq_id = s.scalar(select(User.id).where(User.email == hq_email))
        info["hq_ctx"] = load_context(s, tid, hq_id)
        # A staff member other than the HQ owner who can see the order, if the tenant has one.
        order = s.get(Transaction, orders["me"])
        info["location_id"] = order.location_id
        scoped = None
        for role in ("location_manager", "franchisee_owner"):
            for email in _emails(cfg, role):
                uid = s.scalar(select(User.id).where(User.email == email))
                ctx = load_context(s, tid, uid)
                if ctx.can_see_location(order.location_id):
                    scoped = (email, ctx)
        other_scope = None
        for email in _emails(cfg, "location_manager"):
            uid = s.scalar(select(User.id).where(User.email == email))
            ctx = load_context(s, tid, uid)
            if not ctx.can_see_location(order.location_id):
                other_scope = email
    info.update(
        orders=orders,
        cids=cids,
        hq=login(api, cfg.slug, hq_email),
        me=login(api, cfg.slug, customers[0]),
        other=login(api, cfg.slug, customers[1]),
        scoped_email=scoped[0] if scoped else None,
        scoped_ctx=scoped[1] if scoped else None,
        scoped=login(api, cfg.slug, scoped[0]) if scoped else None,
        out_of_scope=login(api, cfg.slug, other_scope) if other_scope else None,
    )

    def set_total(paise: int, label: str = "me") -> None:
        with tenant_session(tid, app_engine) as s:
            order = s.get(Transaction, orders[label])
            payment = s.scalars(
                select(Payment).where(Payment.transaction_id == order.id).order_by(Payment.id)
            ).first()
            saved.setdefault(
                orders[label], (order.total_paise, payment.id, payment.amount_paise, payment.status)
            )
            order.total_paise = paise
            payment.amount_paise = paise
            payment.status = "captured"

    def new_pending(
        value: int = 5000,
        *,
        who: str = "me",
        messages: tuple[str, ...] = ("The food arrived cold.",),
        language: str | None = None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        cid = uuid.uuid4()
        with tenant_session(tid, app_engine) as s:
            s.add(
                Case(
                    id=cid,
                    tenant_id=tid,
                    customer_id=cids[who],
                    transaction_id=orders[who],
                    category=None,
                    status="awaiting_approval",
                    channel="app",
                    opened_at=datetime.now(UTC),
                    language=language,
                )
            )
            s.flush()
            ticket = Ticket(
                id=uuid.uuid4(),
                tenant_id=tid,
                customer_id=cids[who],
                transaction_id=orders[who],
                case_id=cid,
                category="x",
                status="open",
                channel="app",
                opened_at=datetime.now(UTC),
            )
            s.add(ticket)
            s.flush()
            for body in messages:
                s.add(
                    TicketMessage(
                        tenant_id=tid,
                        ticket_id=ticket.id,
                        author="customer",
                        body=body,
                        sent_at=datetime.now(UTC),
                    )
                )
            params = {"transaction_id": str(orders[who]), "value_paise": value, "reason": "x"}
            p = create_proposal(
                s, tid, case_id=cid, action="free_item_voucher", params=params, reason="p"
            )
            pid = p.id
        made.append(cid)
        return cid, pid

    info.update(set_total=set_total, new_pending=new_pending)
    yield info
    with tenant_session(tid, maint_engine) as s:
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id.in_(made)))
    with tenant_session(tid, app_engine) as s:
        for oid, (total, pay_id, pay_amount, pay_status) in saved.items():
            s.get(Transaction, oid).total_paise = total
            p = s.get(Payment, pay_id)
            p.amount_paise, p.status = pay_amount, pay_status


def _suggest(a, pid, headers=None):
    return a["api"].get(f"/approvals/{pid}/ask-customer", headers=headers or a["hq"])


def _ask(a, pid, options=None, headers=None):
    if options is None:
        sug = _suggest(a, pid).json()
        assert sug["can_ask"], sug
        options = [{"action": o["action"]} for o in sug["options"]]
    return a["api"].post(
        f"/approvals/{pid}/ask-customer", headers=headers or a["hq"], json={"options": options}
    )


def _offer_row(a, pid) -> ProposalOffer:
    with tenant_session(a["tid"], a["engine"]) as s:
        row = s.scalar(select(ProposalOffer).where(ProposalOffer.proposal_id == pid))
        s.expunge_all()
        return row


def _decision_rows(a, pid) -> int:
    with tenant_session(a["tid"], a["engine"]) as s:
        return len(list(s.scalars(select(Approval.id).where(Approval.proposal_id == pid))))


# --- asking ---------------------------------------------------------------------------------


def test_default_suggestion_is_a_voucher_and_a_refund_at_their_maximums(ask):
    ask["set_total"](RS_149)
    _, pid = ask["new_pending"]()
    sug = _suggest(ask, pid).json()
    if not sug["can_ask"]:
        pytest.skip(f"this order allows no choice: {sug['blocked_reason']}")
    by = {o["action"]: o["amount_paise"] for o in sug["options"]}
    assert set(by) == {"free_item_voucher", "refund"}
    with tenant_session(ask["tid"], ask["engine"]) as s:
        facts = order_facts(s, ask["orders"]["me"])[1]
    assert by["free_item_voucher"] <= RS_149  # never above what the order cost
    assert by["free_item_voucher"] <= facts.settings["voucher_max_paise"]
    assert by["refund"] <= 7450  # half of Rs 149, in integer paise
    assert by["refund"] == min(7450, facts.refundable_paise)
    assert all(type(v) is int for v in by.values())


def test_asking_stores_the_offer_audits_codes_and_amounts_and_blocks_approval(ask):
    cid, pid = ask["new_pending"]()
    resp = _ask(ask, pid)
    assert resp.status_code == 201, resp.text
    row = _offer_row(ask, pid)
    assert len(row.options) == 2 and row.chosen_code is None
    assert row.expires_at - row.asked_at == timedelta(days=3)  # the setting's default
    # Waiting: nobody can approve, by API or by engine call; nothing was decided or paid.
    blocked = ask["api"].post(
        f"/approvals/{pid}/decision", headers=ask["hq"], json={"decision": "approved"}
    )
    assert blocked.status_code == 409 and "waiting for the customer" in blocked.text
    with tenant_session(ask["tid"], ask["engine"]) as s, pytest.raises(WaitingForCustomer):
        decide(s, ask["hq_ctx"], pid, "approved", datetime.now(UTC))
    assert _decision_rows(ask, pid) == 0
    with tenant_session(ask["tid"], ask["engine"]) as s:
        p = s.get(ActionProposal, pid)
        assert proposal_hash_is_intact(p) and p.amount_paise == 5000
        audit = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == cid, AuditEvent.event == "case.options_offered"
            )
        ).one()
    assert set(audit.payload) == {"proposal_id", "options"}
    assert all(set(o) == {"code", "amount_paise"} for o in audit.payload["options"])
    # Switching to another remedy is also held while the customer is being asked.
    sw = ask["api"].post(
        f"/approvals/{pid}/switch",
        headers=ask["hq"],
        json={"action": "free_item_voucher", "amount_paise": 2000, "note": "x"},
    )
    assert sw.status_code == 409
    # A rejection stays possible: it withdraws the request.
    rej = ask["api"].post(
        f"/approvals/{pid}/decision", headers=ask["hq"], json={"decision": "rejected"}
    )
    assert rej.status_code == 200, rej.text


def test_a_second_question_on_the_same_proposal_is_refused(ask):
    _, pid = ask["new_pending"]()
    assert _ask(ask, pid).status_code == 201
    assert _ask(ask, pid, [{"action": "free_item_voucher"}] * 2).status_code in (409, 422)
    assert _suggest(ask, pid).json()["can_ask"] is False


def test_customers_cannot_ask_and_unknown_or_decided_proposals_fail(ask):
    _, pid = ask["new_pending"]()
    assert _ask(ask, pid, headers=ask["me"]).status_code == 403
    assert _suggest(ask, pid, headers=ask["me"]).status_code == 403
    assert _ask(ask, uuid.uuid4()).status_code == 404
    done = ask["api"].post(
        f"/approvals/{pid}/decision", headers=ask["hq"], json={"decision": "rejected"}
    )
    assert done.status_code == 200
    assert _ask(ask, pid).status_code == 409  # not pending any more


def test_staff_outside_the_orders_scope_get_404(ask):
    if ask["out_of_scope"] is None:
        pytest.skip("every manager of this tenant can see the order")
    _, pid = ask["new_pending"]()
    assert _ask(ask, pid, headers=ask["out_of_scope"]).status_code == 404
    assert _suggest(ask, pid, headers=ask["out_of_scope"]).status_code == 404
    assert _offer_row(ask, pid) is None


def test_amounts_outside_the_rule_are_422_and_leave_nothing_behind(ask):
    ask["set_total"](RS_149)
    _, pid = ask["new_pending"]()
    sug = _suggest(ask, pid).json()
    if not sug["can_ask"]:
        pytest.skip("no choice on this order")
    top = {o["action"]: o["amount_paise"] for o in sug["options"]}
    voucher, refund = "free_item_voucher", "refund"
    bad = [
        [{"action": voucher, "amount_paise": top[voucher] + 100}, {"action": refund}],
        [{"action": voucher}, {"action": refund, "amount_paise": top[refund] + 1}],
        [{"action": voucher, "amount_paise": 1050}, {"action": refund}],  # not whole rupees
        [{"action": voucher, "amount_paise": 100}, {"action": refund}],  # below the minimum
        [{"action": voucher, "amount_paise": 12.5}, {"action": refund}],  # a float
        [{"action": voucher, "amount_paise": True}, {"action": refund}],  # a bool
        [{"action": voucher}, {"action": voucher}],  # the same option twice
        [{"action": voucher}, {"action": "loyalty_credit", "amount_paise": 500}],
        [{"action": voucher}, {"action": "cash_bonus", "amount_paise": 500}],
        [{"action": voucher}],  # not two
        [{"action": voucher}, {"action": refund}, {"action": refund, "amount_paise": 500}],
    ]
    for options in bad:
        resp = _ask(ask, pid, options)
        assert resp.status_code == 422, (options, resp.text)
    assert _offer_row(ask, pid) is None
    # Explicit amounts inside the rule are accepted and stored as asked.
    ok = _ask(ask, pid, [{"action": voucher, "amount_paise": 1000}, {"action": refund}])
    assert ok.status_code == 201, ok.text
    assert {o["amount_paise"] for o in ok.json()["options"]} == {1000, top[refund]}


def test_a_delivery_app_order_offers_no_refund(ask, app_engine):
    tid = ask["tid"]
    with tenant_session(tid, app_engine) as s:
        row = s.scalar(
            select(TenantSetting).where(
                TenantSetting.key == "refund_channel",
                TenantSetting.brand_id.is_(None),
                TenantSetting.location_id.is_(None),
            )
        )
        before = None if row is None else row.value
        if row is None:
            s.add(TenantSetting(tenant_id=tid, key="refund_channel", value="aggregator_only"))
        else:
            row.value = "aggregator_only"
    try:
        with tenant_session(tid, app_engine) as s:
            if (
                order_facts(s, ask["orders"]["me"])[1].settings["refund_channel"]
                == "tenant_gateway"
            ):
                pytest.skip("a narrower setting keeps this order on the tenant gateway")
        _, pid = ask["new_pending"]()
        sug = _suggest(ask, pid).json()
        assert not any(o["action"] == "refund" for o in sug["options"])
        assert sug["can_ask"] is False  # one kind left: no choice to put to the customer
        resp = _ask(ask, pid, [{"action": "free_item_voucher"}, {"action": "refund"}])
        assert resp.status_code == 422 and "refund" in resp.text
        assert _offer_row(ask, pid) is None
    finally:
        with tenant_session(tid, app_engine) as s:
            row = s.scalar(
                select(TenantSetting).where(
                    TenantSetting.key == "refund_channel",
                    TenantSetting.brand_id.is_(None),
                    TenantSetting.location_id.is_(None),
                )
            )
            if before is None:
                s.delete(row)
            else:
                row.value = before


@pytest.mark.parametrize(
    "message",
    [
        "I had an allergic reaction after eating this.",
        "My son was sick and vomiting after the meal.",
        "There was a cockroach in the food",
        "khane mein keeda tha, ulti ho gayi",
        "खाने में कीड़ा निकला",
    ],
)
def test_allergen_illness_and_foreign_object_reports_are_never_offered_compensation(ask, message):
    _, pid = ask["new_pending"](messages=("The order was wrong.", message))
    sug = _suggest(ask, pid).json()
    assert sug["can_ask"] is False and "manager" in sug["blocked_reason"]
    resp = _ask(ask, pid, [{"action": "free_item_voucher"}, {"action": "refund"}])
    assert resp.status_code == 409 and "manager" in resp.text
    assert _offer_row(ask, pid) is None


# --- the customer's side --------------------------------------------------------------------


def test_the_customer_sees_two_options_and_nobody_else_does(ask):
    cid, pid = ask["new_pending"]()
    assert _ask(ask, pid).status_code == 201
    view = ask["api"].get(f"/cases/{cid}/offer", headers=ask["me"]).json()
    assert view["state"] == "open" and len(view["options"]) == 2
    assert {o["kind"] for o in view["options"]} <= {"voucher", "refund"}
    assert all(o["approval"] == "team" for o in view["options"])  # a person reviews every pick
    # Another customer, staff, and an unknown case: never the offer.
    assert ask["api"].get(f"/cases/{cid}/offer", headers=ask["other"]).status_code == 404
    assert ask["api"].get(f"/cases/{cid}/offer", headers=ask["hq"]).status_code == 403
    assert ask["api"].get(f"/cases/{uuid.uuid4()}/offer", headers=ask["me"]).status_code == 404
    other = ask["api"].put(
        f"/cases/{cid}/offer-choice",
        headers=ask["other"],
        json={"option": view["options"][0]["code"]},
    )
    assert other.status_code == 404
    assert _offer_row(ask, pid).chosen_code is None


@pytest.mark.parametrize("lang", ["en", "hi-Latn", "hi"])
def test_customer_text_is_a_template_in_the_case_language(ask, lang):
    cid, pid = ask["new_pending"](language=lang)
    assert _ask(ask, pid).status_code == 201
    view = ask["api"].get(f"/cases/{cid}/offer", headers=ask["me"]).json()
    text_all = " ".join([view["heading"], view["intro"], view["expires_note"]])
    assert view["heading"] and view["intro"] and "3" in view["expires_note"]
    assert bool(re.search(r"[ऀ-ॿ]", text_all)) == (lang == "hi")
    if lang == "en":
        assert "not a promise" in view["intro"] and "team member will review" in view["intro"]
    for banned in ("issued", "processed", "approved", "jaari kar diya", "process kar diya"):
        assert banned not in text_all.lower()
    for o in view["options"]:
        assert "₹" in o["summary"]


def test_the_three_languages_read_differently(ask):
    seen = set()
    for lang in ("en", "hi-Latn", "hi"):
        cid, pid = ask["new_pending"](language=lang)
        assert _ask(ask, pid).status_code == 201
        seen.add(ask["api"].get(f"/cases/{cid}/offer", headers=ask["me"]).json()["intro"])
    assert len(seen) == 3


def test_a_pick_must_be_one_of_the_stored_options_and_works_once(ask):
    cid, pid = ask["new_pending"]()
    assert _ask(ask, pid).status_code == 201
    view = ask["api"].get(f"/cases/{cid}/offer", headers=ask["me"]).json()
    code = view["options"][0]["code"]
    for bad in ("voucher_99999999", "refund_1", "cash", code.upper()):
        r = ask["api"].put(f"/cases/{cid}/offer-choice", headers=ask["me"], json={"option": bad})
        assert r.status_code == 422, (bad, r.text)
    assert (
        ask["api"]
        .put(f"/cases/{cid}/offer-choice", headers=ask["hq"], json={"option": code})
        .status_code
        == 403
    )
    ok = ask["api"].put(f"/cases/{cid}/offer-choice", headers=ask["me"], json={"option": code})
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "chosen" and ok.json()["options"] == []
    again = ask["api"].put(f"/cases/{cid}/offer-choice", headers=ask["me"], json={"option": code})
    assert again.status_code == 409


def test_a_pick_supersedes_the_old_proposal_and_needs_a_person(ask):
    cid, pid = ask["new_pending"]()
    assert _ask(ask, pid).status_code == 201
    row = _offer_row(ask, pid)
    chosen = next(o for o in row.options if o["action"] == "refund")
    with tenant_session(ask["tid"], ask["engine"]) as s:
        old_hash = s.get(ActionProposal, pid).payload_hash
    resp = ask["api"].put(
        f"/cases/{cid}/offer-choice", headers=ask["me"], json={"option": chosen["code"]}
    )
    assert resp.status_code == 200, resp.text
    row = _offer_row(ask, pid)
    assert row.chosen_code == chosen["code"] and row.new_proposal_id is not None
    new_id = row.new_proposal_id
    with tenant_session(ask["tid"], ask["engine"]) as s:
        new, old = s.get(ActionProposal, new_id), s.get(ActionProposal, pid)
        # Built by the same code path: its own hash, the amount from the stored offer, and the
        # staff member who asked as proposer (so four-eyes applies to them).
        assert (new.action, new.amount_paise) == ("refund", chosen["amount_paise"])
        assert new.payload_hash != old_hash and old.payload_hash == old_hash
        assert proposal_hash_is_intact(new) and proposal_hash_is_intact(old)
        assert new.proposed_by == ask["hq_ctx"].user_id
        link = s.scalars(
            select(ProposalSupersession).where(ProposalSupersession.old_proposal_id == pid)
        ).one()
        assert link.new_proposal_id == new_id
        assert s.scalar(select(Approval.id).where(Approval.proposal_id == new_id)) is None
        events = [
            e.event
            for e in s.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id == cid, AuditEvent.event.like("case.options_%")
                )
            )
        ]
        chosen_audit = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == cid, AuditEvent.event == "case.options_chosen"
            )
        ).one()
        assert sorted(events) == ["case.options_chosen", "case.options_offered"]
        assert set(chosen_audit.payload) == {
            "option", "amount_paise", "old_proposal_id", "new_proposal_id",
        }  # fmt: skip
    # Hash binding: the old proposal can no longer be decided, and the asker cannot approve the
    # new one (four-eyes, per approvals.decide).
    with tenant_session(ask["tid"], ask["engine"]) as s, pytest.raises(AlreadyDecided):
        decide(s, ask["hq_ctx"], pid, "approved", datetime.now(UTC))
    from app.engine.approvals import Forbidden

    with tenant_session(ask["tid"], ask["engine"]) as s, pytest.raises(Forbidden):
        decide(s, ask["hq_ctx"], new_id, "approved", datetime.now(UTC))
    # It is in the staff queue with its reason, as a pending approval, not paid or auto-approved.
    queue = ask["api"].get("/cases/queue", headers=ask["hq"]).json()
    item = next(i for i in queue if i["case_id"] == str(cid))
    assert item["reason_code"] == "customer_chose" and item["proposal_id"] == str(new_id)
    pending = ask["api"].get("/approvals", headers=ask["hq"]).json()
    mine = [p for p in pending if p["case_id"] == str(cid)]
    assert [p["proposal_id"] for p in mine] == [str(new_id)]
    assert mine[0]["queue_reason"] == "customer_chose"
    # A different person reviews it and approves (decide only records; nothing is executed here).
    if ask["scoped_ctx"] is not None:
        with tenant_session(ask["tid"], ask["engine"]) as s:
            approval = decide(s, ask["scoped_ctx"], new_id, "approved", datetime.now(UTC))
            usable = check_usable(approval, s.get(ActionProposal, new_id), datetime.now(UTC))
            assert usable.ok
            # The approval is bound to the new proposal's hash, not the old one's.
            assert approval.payload_hash == s.get(ActionProposal, new_id).payload_hash != old_hash
            assert not check_usable(approval, s.get(ActionProposal, pid), datetime.now(UTC)).ok


def test_the_answer_is_write_once_in_the_database(ask, app_engine):
    cid, pid = ask["new_pending"]()
    assert _ask(ask, pid).status_code == 201
    code = _offer_row(ask, pid).options[0]["code"]
    assert (
        ask["api"]
        .put(f"/cases/{cid}/offer-choice", headers=ask["me"], json={"option": code})
        .status_code
        == 200
    )
    for sql in (
        "UPDATE proposal_offers SET chosen_code = 'x' WHERE proposal_id = :p",
        "UPDATE proposal_offers SET options = '[]'::jsonb WHERE proposal_id = :p",
    ):
        with pytest.raises(DBAPIError), tenant_session(ask["tid"], app_engine) as s:
            s.execute(text(sql), {"p": pid})
    with pytest.raises(DBAPIError), tenant_session(ask["tid"], app_engine) as s:
        s.execute(text("DELETE FROM proposal_offers WHERE proposal_id = :p"), {"p": pid})


# --- the queue and the timeout --------------------------------------------------------------


def test_an_open_question_keeps_the_case_out_of_the_queue(ask):
    cid, pid = ask["new_pending"]()
    before = ask["api"].get("/cases/queue", headers=ask["hq"]).json()
    assert any(i["case_id"] == str(cid) for i in before)
    assert _ask(ask, pid).status_code == 201
    during = ask["api"].get("/cases/queue", headers=ask["hq"]).json()
    assert not any(i["case_id"] == str(cid) for i in during)
    waiting = [
        p
        for p in ask["api"].get("/approvals", headers=ask["hq"]).json()
        if p["case_id"] == str(cid)
    ]
    assert waiting[0]["offer"]["state"] == "open"  # still listed, as "waiting for the customer"


def test_no_answer_returns_the_case_to_a_person_with_the_proposal_undecided(ask):
    cid, pid = ask["new_pending"]()
    asked_long_ago = datetime.now(UTC) - timedelta(days=4)
    with tenant_session(ask["tid"], ask["engine"]) as s:
        offer = ask_customer.ask_customer(
            s, ask["hq_ctx"], pid, [{"action": "free_item_voucher"}, {"action": "refund"}],
            asked_long_ago,
        )  # fmt: skip
        assert offer.expires_at < datetime.now(UTC)
    queue = ask["api"].get("/cases/queue", headers=ask["hq"]).json()
    item = next(i for i in queue if i["case_id"] == str(cid))
    assert item["reason_code"] == "no_customer_answer" and item["proposal_id"] == str(pid)
    view = ask["api"].get(f"/cases/{cid}/offer", headers=ask["me"]).json()
    assert view["state"] == "expired" and view["options"] == []
    late = ask["api"].put(
        f"/cases/{cid}/offer-choice", headers=ask["me"], json={"option": "voucher_1000"}
    )
    assert late.status_code == 409
    assert _decision_rows(ask, pid) == 0  # undecided, and the person can now decide it
    with tenant_session(ask["tid"], ask["engine"]) as s:
        assert ask_customer.proposal_is_pending(s, pid)
        # Fair use stays a warning: a person can approve (here, via the scoped staff member or,
        # failing one, the asker is refused by four-eyes only when they proposed it themselves).
        approver = ask["scoped_ctx"] or ask["hq_ctx"]
        approval = decide(s, approver, pid, "approved", datetime.now(UTC))
        assert approval.decision == "approved"
