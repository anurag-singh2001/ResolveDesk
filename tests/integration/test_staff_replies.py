"""S7.6 templated staff replies and close-with-reason, for every tenant, never naming one.

Who may act comes from the tenant folder's users (role and outlets). A case with a ticket and
the customer's first message is planted per test; the timeline is read as the customer.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES, TEMPLATES, t
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Customer,
    Execution,
    Location,
    RefundOperation,
    Ticket,
    TicketMessage,
    Transaction,
    User,
    Verification,
)
from app.core.money import format_inr
from app.core.settings_resolver import effective_settings
from app.core.tenancy import load_context, tenant_id_for
from app.engine import lifecycle
from app.engine.approvals import decide
from app.engine.privacy import close_text
from app.engine.proposals import create_proposal
from app.engine.staff_actions import CLOSE_REASONS, NOTE_MAX_LENGTH, TEMPLATE_IDS
from tests.helpers import login


def _staff(cfg, role):
    return [u for u in cfg.users if u.role == role]


@pytest.fixture
def world(api, app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        locs = {slug: lid for lid, slug in s.execute(select(Location.id, Location.slug)).all()}
        ids = {e: i for i, e in s.execute(select(User.id, User.email)).all()}
        by_loc = {}
        for loc_id in locs.values():
            order = s.scalar(
                select(Transaction)
                .where(Transaction.location_id == loc_id, Transaction.total_paise >= 1000)
                .order_by(Transaction.id)
            )
            if order is not None:
                by_loc[loc_id] = (order.id, order.customer_id)
        # The demo customer can log in: their order is the one every customer-side check uses.
        demo = next(u for u in cfg.users if u.role == "customer")
        demo_cust = s.scalar(
            select(Customer.id)
            .join(User, User.id == Customer.user_id)
            .where(User.email == demo.email)
        )
        mine = s.scalar(
            select(Transaction)
            .where(Transaction.customer_id == demo_cust)
            .order_by(Transaction.placed_at.desc())
        )
        by_loc[mine.location_id] = (mine.id, demo_cust)
        demo_loc = mine.location_id
    cases: list[uuid.UUID] = []
    w = {"demo_loc": demo_loc,
        "api": api, "cfg": cfg, "tid": tid, "engine": app_engine, "locs": locs, "ids": ids,
        "order_at": by_loc, "cases": cases,
    }  # fmt: skip
    yield w


def _cleanup(w, maint_engine):
    with tenant_session(w["tid"], maint_engine) as s:
        mine = select(ActionProposal.id).where(ActionProposal.case_id.in_(w["cases"]))
        s.execute(delete(RefundOperation).where(RefundOperation.proposal_id.in_(mine)))
        s.execute(
            delete(Ticket).where(Ticket.tenant_id == w["tid"], Ticket.case_id.in_(w["cases"]))
        )
        s.execute(delete(Case).where(Case.tenant_id == w["tid"], Case.id.in_(w["cases"])))


@pytest.fixture(autouse=True)
def _teardown(world, maint_engine):
    yield
    _cleanup(world, maint_engine)


def _case(w, loc_id, status="escalated", language=None) -> uuid.UUID:
    order_id, customer_id = w["order_at"][loc_id]
    cid = uuid.uuid4()
    now = datetime.now(UTC)
    with tenant_session(w["tid"], w["engine"]) as s:
        s.add(
            Case(
                id=cid, tenant_id=w["tid"], customer_id=customer_id, transaction_id=order_id,
                status=status, channel="app", opened_at=now, language=language,
            )
        )  # fmt: skip
        s.flush()
        tk = Ticket(
            id=uuid.uuid4(), tenant_id=w["tid"], customer_id=customer_id, transaction_id=order_id,
            case_id=cid, category="unknown", status="open", channel="app", opened_at=now,
        )  # fmt: skip
        s.add(tk)
        s.flush()
        s.add(
            TicketMessage(
                tenant_id=w["tid"],
                ticket_id=tk.id,
                author="customer",
                body="Item missing",
                sent_at=now,
            )
        )
    w["cases"].append(cid)
    return cid


def _loc(w):
    return w["demo_loc"]


def _hq(w):
    return login(w["api"], w["cfg"].slug, _staff(w["cfg"], "hq_owner")[0].email)


def _reply(w, headers, cid, template="looking_into", **extra):
    return w["api"].post(
        f"/cases/{cid}/staff-reply", json={"template_id": template, **extra}, headers=headers
    )


def _customer_headers(w, cid):
    with tenant_session(w["tid"], w["engine"]) as s:
        case = s.get(Case, cid)
        email = s.scalar(
            select(User.email)
            .join(Customer, Customer.user_id == User.id)
            .where(Customer.id == case.customer_id)
        )
    return login(w["api"], w["cfg"].slug, email)


def test_templates_exist_in_every_language_and_list_matches():
    for tid, (_label, key) in TEMPLATE_IDS.items():
        assert set(TEMPLATES[key]) == set(LANGUAGES), tid
    for reason in CLOSE_REASONS:
        assert set(TEMPLATES[f"close.{reason}"]) == set(LANGUAGES)


def test_template_list_is_rendered_in_the_case_language(world):
    w = world
    headers = _hq(w)
    for lang in LANGUAGES:
        cid = _case(w, _loc(w), language=lang)
        r = w["api"].get(f"/cases/{cid}/reply-templates", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["language"] == lang
        ids = {x["id"]: x["preview"] for x in body["templates"]}
        assert ids["looking_into"] == t("staff.looking_into", lang)
        # no refund is in progress: that template is not offered
        assert "refund_processing" not in ids
        assert {x["id"] for x in body["close_reasons"]} == set(CLOSE_REASONS)
        assert body["note_max_length"] == NOTE_MAX_LENGTH


def test_reply_reaches_the_customer_timeline_in_the_case_language(world):
    w = world
    for lang in LANGUAGES:
        cid = _case(w, _loc(w), language=lang)
        r = _reply(w, _hq(w), cid, "share_photo")
        assert r.status_code == 200 and r.json()["sent"] is True
        tl = w["api"].get(f"/cases/{cid}/timeline", headers=_customer_headers(w, cid)).json()
        assert t("staff.share_photo", lang) in [s["text"] for s in tl]
        assert t("tl.staff.title", lang) in [s["title"] for s in tl]


def test_note_is_labelled_separate_verbatim_and_audited_without_words(world):
    w = world
    cid = _case(w, _loc(w), language="hi-Latn")
    note = "Hamara rider aapke area mein hai"
    assert _reply(w, _hq(w), cid, note=note).status_code == 200
    tl = w["api"].get(f"/cases/{cid}/timeline", headers=_customer_headers(w, cid)).json()
    steps = [s for s in tl if s["title"] == t("tl.staff_note.title", "hi-Latn")]
    assert [s["text"] for s in steps] == [note]  # verbatim, under its own label
    template_text = t("staff.looking_into", "hi-Latn")
    assert all(note not in s["text"] for s in tl if s["text"] == template_text)
    with tenant_session(w["tid"], w["engine"]) as s:
        ev = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == cid, AuditEvent.event == "case.staff_reply"
            )
        ).one()
        assert ev.payload == {"template_id": "looking_into", "addendum_length": len(note)}
        assert note not in str(ev.payload)
    # staff see it too
    detail = w["api"].get(f"/cases/{cid}", headers=_hq(w)).json()
    assert [m["kind"] for m in detail["staff_messages"]] == ["template", "note"]
    assert (
        w["api"].get(f"/cases/{cid}", headers=_customer_headers(w, cid)).json()["staff_messages"]
        == []
    )


@pytest.mark.parametrize(
    "note",
    [
        "Your refund is on its way",
        "रिफ़ंड हो गया",
        "we paid you Rs 500",
        "sent ₹200 to your wallet",
        "see https://example.test/x",
        "mail me at a@b.c",
        "x" * (NOTE_MAX_LENGTH + 1),
    ],
)
def test_note_that_states_money_links_or_is_too_long_is_refused(world, note):
    w = world
    cid = _case(w, _loc(w))
    assert _reply(w, _hq(w), cid, note=note).status_code == 422
    with tenant_session(w["tid"], w["engine"]) as s:
        n = s.scalar(
            select(TicketMessage.id)
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .where(Ticket.case_id == cid, TicketMessage.author == "staff")
        )
        assert n is None


def test_ordinary_words_are_not_mistaken_for_money(world):
    w = world
    cid = _case(w, _loc(w))
    assert (
        _reply(w, _hq(w), cid, note="Your orders will be checked by the kitchen").status_code == 200
    )


def test_unknown_template_and_inapplicable_refund_template_are_422(world):
    w = world
    cid = _case(w, _loc(w))
    assert _reply(w, _hq(w), cid, "nonsense").status_code == 422
    assert _reply(w, _hq(w), cid, "refund_processing").status_code == 422


def test_double_submit_is_one_message(world):
    w = world
    cid = _case(w, _loc(w))
    key = uuid.uuid4().hex
    first = _reply(w, _hq(w), cid, note="Thanks for waiting", idempotency_key=key)
    second = _reply(w, _hq(w), cid, note="Thanks for waiting", idempotency_key=key)
    assert first.json()["sent"] is True and second.json()["sent"] is False
    # no key at all: the same submit twice is still one message
    _reply(w, _hq(w), cid, "share_photo")
    _reply(w, _hq(w), cid, "share_photo")
    with tenant_session(w["tid"], w["engine"]) as s:
        rows = s.scalars(
            select(TicketMessage)
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .where(Ticket.case_id == cid, TicketMessage.author == "staff")
        ).all()
        assert sorted(r.template_id or "note" for r in rows) == [
            "looking_into",
            "note",
            "share_photo",
        ]
        audits = s.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == cid, AuditEvent.event == "case.staff_reply"
            )
        ).all()
        assert len(audits) == 2


def test_refund_processing_template_only_while_a_refund_is_really_processing(world):
    w = world
    loc = _loc(w)
    cid = _case(w, loc, status="open")
    order_id = w["order_at"][loc][0]
    hq_user = _staff(w["cfg"], "hq_owner")[0]
    with tenant_session(w["tid"], w["engine"]) as s:
        proposal = create_proposal(
            s, w["tid"], case_id=cid, action="refund", reason="p",
            params={"transaction_id": str(order_id), "reason": "x", "amount_paise": 1000},
        )  # fmt: skip
        s.flush()
        lifecycle.proposal_made(s, w["tid"], s.get(Case, cid), proposal.id, datetime.now(UTC))
        pid = proposal.id
    headers = _hq(w)
    with tenant_session(w["tid"], w["engine"]) as s:
        from app.core.models import Approval

        auto = s.scalar(select(Approval.id).where(Approval.proposal_id == pid))
    listed = w["api"].get(f"/cases/{cid}/reply-templates", headers=headers).json()
    ids = {x["id"] for x in listed["templates"]}
    if auto is None:  # undecided: no refund is processing yet
        assert "refund_processing" not in ids
        assert _reply(w, headers, cid, "refund_processing").status_code == 422
        # and closing would strand the proposal
        assert (
            w["api"]
            .post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=headers)
            .status_code
            == 409
        )
        with tenant_session(w["tid"], w["engine"]) as s:
            ctx = load_context(s, w["tid"], w["ids"][hq_user.email])
            decide(s, ctx, pid, "approved", datetime.now(UTC))
    listed = w["api"].get(f"/cases/{cid}/reply-templates", headers=headers).json()
    mine = {x["id"]: x["preview"] for x in listed["templates"]}
    assert mine["refund_processing"] == t("staff.refund_processing", "en", amount=format_inr(1000))
    assert _reply(w, headers, cid, "refund_processing").status_code == 200
    # approved but not executed: still a payout in flight, so closing is refused
    r = w["api"].post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=headers)
    assert r.status_code == 409
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.get(Case, cid).status != "closed"


def test_close_with_each_reason_is_stored_audited_and_shown_to_the_customer(world):
    w = world
    for reason in CLOSE_REASONS:
        cid = _case(w, _loc(w), language="hi")
        r = w["api"].post(f"/cases/{cid}/close", json={"reason": reason}, headers=_hq(w))
        assert r.status_code == 200, r.text
        with tenant_session(w["tid"], w["engine"]) as s:
            case = s.get(Case, cid)
            assert (case.status, case.close_reason) == ("closed", reason)
            assert case.closed_at is not None and case.closed_by_user_id is not None
            ev = s.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id == cid, AuditEvent.event == "case.closed"
                )
            ).one()
            assert ev.payload == {"reason": reason}
            assert s.scalar(select(Ticket.status).where(Ticket.case_id == cid)) == "closed"
        cust = _customer_headers(w, cid)
        tl = w["api"].get(f"/cases/{cid}/timeline", headers=cust).json()
        with tenant_session(w["tid"], w["engine"]) as s:
            expected = close_text(reason, effective_settings(s), "hi")
        assert tl[-1]["text"] == expected
        out = w["api"].get(f"/cases/{cid}", headers=cust).json()
        assert out["stage"] == "closed" and out["message"] == expected


@pytest.mark.parametrize("lang", LANGUAGES)
def test_no_remedy_close_text_gives_a_reason_the_contact_and_the_helpline(lang):
    """M2: no legal-sounding 'remedy', no 'compensation' word in Hindi; a way to contest."""
    settings = {
        "privacy_contact_name": "Desk",
        "privacy_contact_email": "desk@example.test",
        "grievance_target_days": 30,
    }
    text = close_text("no_remedy", settings, lang)
    assert "Desk (desk@example.test)" in text and "1915" in text
    assert "consumerhelpline.gov.in" in text and "30" in text and "{" not in text
    assert "remedy" not in text.lower() and "muaavza" not in text and "मुआवज़ा" not in text
    # With no contact set the sentence drops that clause instead of pointing at nobody.
    bare = close_text(
        "no_remedy", {**settings, "privacy_contact_email": "", "privacy_contact_name": ""}, lang
    )
    assert "1915" in bare and "{" not in bare and "desk@" not in bare


def test_closed_case_refuses_reply_and_second_close(world):
    w = world
    cid = _case(w, _loc(w))
    h = _hq(w)
    assert (
        w["api"].post(f"/cases/{cid}/close", json={"reason": "duplicate"}, headers=h).status_code
        == 200
    )
    assert (
        w["api"].post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=h).status_code
        == 409
    )
    assert _reply(w, h, cid).status_code == 409
    tpl = w["api"].get(f"/cases/{cid}/reply-templates", headers=h).json()
    assert tpl["closed"] is True


def test_unknown_close_reason_is_422(world):
    w = world
    cid = _case(w, _loc(w))
    assert (
        w["api"].post(f"/cases/{cid}/close", json={"reason": "bored"}, headers=_hq(w)).status_code
        == 422
    )


def test_customers_are_forbidden_and_other_tenant_or_out_of_scope_is_404(world, seeded_history):
    w = world
    cid = _case(w, _loc(w))
    cust = _customer_headers(w, cid)
    assert _reply(w, cust, cid).status_code == 403
    assert (
        w["api"].post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=cust).status_code
        == 403
    )
    assert w["api"].get(f"/cases/{cid}/reply-templates", headers=cust).status_code == 403
    others = [c for c in seeded_history.values() if c.slug != w["cfg"].slug]
    foreign = login(w["api"], others[0].slug, _staff(others[0], "hq_owner")[0].email)
    assert _reply(w, foreign, cid).status_code == 404
    assert (
        w["api"]
        .post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=foreign)
        .status_code
        == 404
    )
    assert w["api"].get(f"/cases/{cid}/reply-templates", headers=foreign).status_code == 404
    # scoped staff cannot act on an outlet they cannot see
    scoped = next((u for u in w["cfg"].users if u.locations and u.role != "hq_owner"), None)
    other_loc = next(
        (
            i
            for slug, i in w["locs"].items()
            if scoped and slug not in scoped.locations and i in w["order_at"]
        ),
        None,
    )
    if other_loc is not None:
        far = _case(w, other_loc)
        sh = login(w["api"], w["cfg"].slug, scoped.email)
        assert _reply(w, sh, far).status_code == 404
        assert (
            w["api"]
            .post(f"/cases/{far}/close", json={"reason": "resolved"}, headers=sh)
            .status_code
            == 404
        )
        near = _case(
            w, next(i for s, i in w["locs"].items() if s in scoped.locations and i in w["order_at"])
        )
        assert _reply(w, sh, near).status_code == 200


@pytest.mark.parametrize(
    "note",
    [
        "Your orders will be checked",
        "Two hours at most",
        "Our partners are helping",
        "We will call you at 4 pm",
    ],
)
def test_everyday_words_are_not_mistaken_for_money(world, note):
    w = world
    cid = _case(w, _loc(w))
    assert _reply(w, _hq(w), cid, note=note).status_code == 200


@pytest.mark.parametrize(
    "note",
    [
        "ref​und soon",  # zero-width character inside the word
        "ｒｅｆｕｎｄ soon",  # full-width letters (NFKC)
        "the amount will arrive",
        "you were charged twice",
        "check your bank",
        "reversed already",
        "call 18001234",
        "paying you now",
    ],
)
def test_disguised_money_talk_is_refused(world, note):
    w = world
    cid = _case(w, _loc(w))
    assert _reply(w, _hq(w), cid, note=note).status_code == 422


def test_same_key_with_different_content_is_refused(world):
    w = world
    cid = _case(w, _loc(w))
    key = uuid.uuid4().hex
    assert _reply(w, _hq(w), cid, idempotency_key=key).status_code == 200
    again = _reply(w, _hq(w), cid, "share_photo", idempotency_key=key)
    assert again.status_code == 409
    same = _reply(w, _hq(w), cid, idempotency_key=key)
    assert same.status_code == 200 and same.json()["sent"] is False


def _refund_case(w, state):
    """An approved refund in a given payout state. Returns the case id."""
    loc = _loc(w)
    cid = _case(w, loc, status="open")
    order_id = w["order_at"][loc][0]
    hq_user = _staff(w["cfg"], "hq_owner")[0]
    with tenant_session(w["tid"], w["engine"]) as s:
        proposal = create_proposal(
            s, w["tid"], case_id=cid, action="refund", reason="p",
            params={"transaction_id": str(order_id), "reason": "x", "amount_paise": 1000},
        )  # fmt: skip
        s.flush()
        lifecycle.proposal_made(s, w["tid"], s.get(Case, cid), proposal.id, datetime.now(UTC))
        pid = proposal.id
    with tenant_session(w["tid"], w["engine"]) as s:
        if s.scalar(select(Approval.id).where(Approval.proposal_id == pid)) is None:
            ctx = load_context(s, w["tid"], w["ids"][hq_user.email])
            decide(s, ctx, pid, "approved", datetime.now(UTC))
    with tenant_session(w["tid"], w["engine"]) as s:
        approval_id = s.scalar(select(Approval.id).where(Approval.proposal_id == pid))
        status = "failed" if state == "failed" else "succeeded"
        ex = Execution(
            tenant_id=w["tid"], proposal_id=pid, approval_id=approval_id,
            idempotency_key=f"s76-{uuid.uuid4().hex}", status=status,
        )  # fmt: skip
        s.add(ex)
        s.flush()
        verdict = {"verified": "verified", "pending_reconciliation": "verified",
                   "mismatch": "mismatch"}.get(state)  # fmt: skip
        if verdict:
            s.add(Verification(tenant_id=w["tid"], execution_id=ex.id, status=verdict))
        if state == "pending_reconciliation":
            s.add(
                RefundOperation(
                    tenant_id=w["tid"], transaction_id=order_id, proposal_id=pid,
                    idempotency_key=f"s76-{uuid.uuid4().hex}", amount_paise=1000,
                    status="pending_reconciliation",
                )
            )  # fmt: skip
    return cid


@pytest.mark.parametrize("state", ["failed", "unverified", "mismatch", "pending_reconciliation"])
def test_close_is_refused_while_a_payout_is_failed_unverified_or_unreconciled(world, state):
    w = world
    cid = _refund_case(w, state)
    r = w["api"].post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=_hq(w))
    assert r.status_code == 409, r.text
    with tenant_session(w["tid"], w["engine"]) as s:
        assert s.get(Case, cid).status != "closed"
        assert s.get(Case, cid).close_reason is None


def test_a_verified_payout_can_be_closed_and_the_customer_still_sees_it_confirmed(world):
    w = world
    cid = _refund_case(w, "verified")
    r = w["api"].post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=_hq(w))
    assert r.status_code == 200, r.text
    out = w["api"].get(f"/cases/{cid}", headers=_customer_headers(w, cid)).json()
    assert out["stage"] == "confirmed"  # the confirmed money fact is not replaced by "closed"


def test_close_is_refused_while_the_ai_is_being_run_again(world):
    from app.engine import ai_rerun

    w = world
    cid = _case(w, _loc(w), status="investigating")
    with tenant_session(w["tid"], w["engine"]) as s:
        s.add(
            AuditEvent(
                tenant_id=w["tid"], actor_type="user", event="case.ai_rerun_requested",
                entity_type="case", entity_id=cid, payload={},
            )
        )  # fmt: skip
    r = w["api"].post(f"/cases/{cid}/close", json={"reason": "resolved"}, headers=_hq(w))
    assert r.status_code == 409
    # and once closed, a re-run cannot be claimed
    other = _case(w, _loc(w))
    assert (
        w["api"].post(f"/cases/{other}/close", json={"reason": "resolved"}, headers=_hq(w))
    ).status_code == 200
    assert ai_rerun.request_rerun(w["engine"], w["tid"], other, trigger="staff") == (
        ai_rerun.NOT_ELIGIBLE
    )


def test_sender_and_closer_must_be_users_of_the_same_tenant(world, seeded_history, maint_engine):
    from sqlalchemy.exc import IntegrityError

    w = world
    cid = _case(w, _loc(w))
    other_cfg = next(c for c in seeded_history.values() if c.slug != w["cfg"].slug)
    with tenant_session(tenant_id_for(other_cfg.slug), maint_engine) as s:
        foreign = s.scalar(select(User.id))
    with pytest.raises(IntegrityError), tenant_session(w["tid"], maint_engine) as s:
        tk = s.scalar(select(Ticket.id).where(Ticket.case_id == cid))
        s.add(
            TicketMessage(
                tenant_id=w["tid"], ticket_id=tk, author="staff", body="x",
                sent_at=datetime.now(UTC), sender_user_id=foreign,
            )
        )  # fmt: skip
    with pytest.raises(IntegrityError), tenant_session(w["tid"], maint_engine) as s:
        s.get(Case, cid).closed_by_user_id = foreign
