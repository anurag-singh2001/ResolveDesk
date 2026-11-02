"""S7.9: the customer chooses between the remedies a pack rule lists. Runs for every tenant and
finds the multi-option category from the tenant's own pack (no tenant is named)."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.actions.base import enabled_actions
from app.agents.schemas import ResolutionDraft
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Customer,
    Ticket,
    Transaction,
    User,
)
from app.core.money import percent_of
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import tenant_id_for
from app.core.verticals import RemedyOptions, load_pack
from app.engine.eligibility import order_facts
from app.engine.graph import _check_draft
from app.engine.proposals import create_proposal
from app.engine.remedy_choice import _approval
from app.engine.resolver import (
    ChoiceOption,
    InvalidRemedyChoice,
    decide_remedy,
    propose_for_case,
    remedy_options,
)
from tests.helpers import login


@pytest.fixture
def ctx(api, app_engine, maint_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    pack = load_pack(cfg.vertical_pack)
    multi = [
        c for c, r in pack.remedies.items() if isinstance(r, RemedyOptions) and len(r.options) > 1
    ]
    single = [c for c, r in pack.remedies.items() if not isinstance(r, RemedyOptions)]
    assert multi, "every vertical pack needs one multi-option rule for this story"
    customer = next(u for u in cfg.users if u.role == "customer")
    with tenant_session(tid, app_engine) as s:
        uid = s.scalar(select(User.id).where(User.email == customer.email))
        cid = s.scalar(select(Customer.id).where(Customer.user_id == uid))
        order = s.scalars(
            select(Transaction)
            .where(Transaction.customer_id == cid, Transaction.total_paise >= 20000)
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
        info = {"tid": tid, "order_id": order.id, "total": order.total_paise, "cid": cid}
    other_cfg = next(c for c in seeded_history.values() if c.slug != cfg.slug)
    with tenant_session(tenant_id_for(other_cfg.slug), app_engine) as s:
        other = s.scalars(select(Transaction.id).limit(1)).one()
    info.update(
        multi=multi[0],
        single=single[0],
        other_tenant_order=other,
        customer=login(api, cfg.slug, customer.email),
        hq=login(api, cfg.slug, next(u.email for u in cfg.users if u.role == "hq_owner")),
    )
    yield info
    with tenant_session(tid, maint_engine) as s:
        ids = select(Case.id).where(Case.tenant_id == tid, Case.transaction_id == info["order_id"])
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(ids)))
        s.execute(
            delete(Case).where(Case.tenant_id == tid, Case.transaction_id == info["order_id"])
        )


def _options(api, c, category=None, order_id=None, headers=None):
    return api.get(
        f"/orders/{order_id or c['order_id']}/remedy-options",
        params={"category": category or c["multi"]},
        headers=headers or c["customer"],
    )


def _report(api, c, category=None, **extra):
    body = {
        "transaction_id": str(c["order_id"]),
        "category": category or c["multi"],
        "message": "Got the wrong thing.",
        **extra,
    }
    return api.post("/cases", headers=c["customer"], json=body)


def _proposal(app_engine, c, case_id):
    with tenant_session(c["tid"], app_engine) as s:
        p = s.scalars(
            select(ActionProposal).where(ActionProposal.case_id == uuid.UUID(case_id))
        ).one()
        return p.action, p.params


def test_options_are_computed_by_code_with_timing_from_settings(api, ctx, app_engine):
    body = _options(api, ctx).json()
    assert body["choice_required"] is True
    by_kind = {o["kind"]: o for o in body["options"]}
    assert set(by_kind) == {"voucher", "refund"}
    with tenant_session(ctx["tid"], app_engine) as s:
        _, facts = order_facts(s, ctx["order_id"])
    pct = min(50, facts.settings["refund_max_percent"])
    expected = min(percent_of(ctx["total"], pct), facts.refundable_paise)
    assert by_kind["refund"]["amount_paise"] == expected
    assert by_kind["refund"]["approval"] == "team"  # refunds are never auto-approved
    assert by_kind["voucher"]["amount_paise"] <= ctx["total"]  # S7.8: never above what was paid
    cap = facts.settings["voucher_auto_approve_max_paise"]
    assert (by_kind["voucher"]["approval"] == "instant") == (
        by_kind["voucher"]["amount_paise"] <= cap
    )
    assert "₹" in by_kind["refund"]["summary"]


def test_options_follow_the_customers_language(api, ctx):
    api.put("/me/preferences", headers=ctx["customer"], json={"language": "hi"})
    try:
        hi = _options(api, ctx).json()["options"][0]
        assert any("ऀ" <= ch <= "ॿ" for ch in hi["summary"])
    finally:
        api.put("/me/preferences", headers=ctx["customer"], json={"language": "en"})


def test_single_option_rule_shows_no_choice(api, ctx):
    body = _options(api, ctx, category=ctx["single"]).json()
    assert body["choice_required"] is False and len(body["options"]) <= 1


def test_other_tenants_order_and_staff_are_refused(api, ctx):
    assert _options(api, ctx, order_id=ctx["other_tenant_order"]).status_code == 404
    assert _options(api, ctx, order_id=uuid.uuid4()).status_code == 404
    assert _options(api, ctx, headers=ctx["hq"]).status_code == 403
    assert _options(api, ctx, category="not_a_category").status_code == 422


def test_refund_choice_creates_a_refund_proposal_within_limits(api, ctx, app_engine):
    resp = _report(api, ctx, remedy_choice="refund_50pct")
    assert resp.status_code == 201, resp.text
    case = resp.json()
    assert case["action"] == "refund" and case["stage"] == "awaiting_approval"
    action, params = _proposal(app_engine, ctx, case["id"])
    with tenant_session(ctx["tid"], app_engine) as s:
        _, facts = order_facts(s, ctx["order_id"])
    assert action == "refund"
    assert params["amount_paise"] <= percent_of(ctx["total"], facts.settings["refund_max_percent"])
    assert params["amount_paise"] <= facts.refundable_paise


def test_voucher_choice_and_default_both_give_a_voucher(api, ctx, maint_engine):
    first = _report(api, ctx, remedy_choice="voucher").json()
    assert first["action"] == "free_item_voucher"
    with tenant_session(ctx["tid"], maint_engine) as s:  # remove it so a second report may open
        s.execute(delete(Ticket).where(Ticket.case_id == uuid.UUID(first["id"])))
        s.execute(delete(Case).where(Case.id == uuid.UUID(first["id"])))
    default = _report(api, ctx).json()  # no pick: the rule's first working option
    assert default["action"] == "free_item_voucher"


def test_a_choice_outside_the_rule_is_422_and_opens_nothing(api, ctx, app_engine):
    for bad, category in (
        ("refund_99pct", None),
        ("cash", None),
        ("refund_50pct", ctx["single"]),  # the rule for this category has one option
    ):
        resp = _report(api, ctx, category=category, remedy_choice=bad)
        assert resp.status_code == 422, (bad, resp.text)
    with tenant_session(ctx["tid"], app_engine) as s:
        assert s.scalar(select(Case.id).where(Case.transaction_id == ctx["order_id"])) is None


def test_choice_is_audited_with_the_option_code_only(api, ctx, app_engine):
    case = _report(api, ctx, remedy_choice="refund_50pct").json()
    with tenant_session(ctx["tid"], app_engine) as s:
        payloads = s.scalars(
            select(AuditEvent.payload).where(
                AuditEvent.event == "case.remedy_choice",
                AuditEvent.entity_id == uuid.UUID(case["id"]),
            )
        ).all()
        stored = s.get(Case, uuid.UUID(case["id"])).remedy_choice
    assert list(payloads) == [{"option": "refund_50pct"}]
    assert stored == "refund_50pct"


def test_undecided_case_takes_a_pick_until_a_proposal_exists(api, ctx, app_engine):
    cid = uuid.uuid4()
    with tenant_session(ctx["tid"], app_engine) as s:
        s.add(
            Case(
                id=cid,
                tenant_id=ctx["tid"],
                customer_id=ctx["cid"],
                transaction_id=ctx["order_id"],
                category=ctx["multi"],
                status="investigating",
                channel="app",
                opened_at=datetime.now(UTC),
            )
        )
    shown = api.get(f"/cases/{cid}/remedy-options", headers=ctx["customer"]).json()
    assert shown["choice_required"] is True
    put = lambda who, opt: api.put(  # noqa: E731
        f"/cases/{cid}/remedy-choice", headers=ctx[who], json={"option": opt}
    )
    assert put("customer", "cash").status_code == 422
    assert put("customer", "refund_50pct").status_code == 200
    # The agent path now sees the pick: the ceiling is the refund, never the voucher.
    with tenant_session(ctx["tid"], app_engine) as s:
        remedy = decide_remedy(s, s.get(Case, cid))
        _, facts = order_facts(s, ctx["order_id"])
        assert remedy.action == "refund"
        with pytest.raises(InvalidRemedyChoice):
            decide_remedy(s, s.get(Case, cid), choice="cash")
        actions = {"refund": enabled_actions(tenant_pack(s).actions)["refund"]}
    over = ResolutionDraft(
        action="refund",
        params={**remedy.params, "amount_paise": remedy.params["amount_paise"] + 100},
        reason="x",
        citations=["a"],
    )
    errs = _check_draft(over, actions, facts, {"a"}, str(ctx["order_id"]), remedy)
    assert any("above what the business rules allow" in e for e in errs)
    swap = ResolutionDraft(action="free_item_voucher", params={}, reason="x", citations=["a"])
    assert _check_draft(swap, actions, facts, {"a"}, str(ctx["order_id"]), remedy)
    # Staff cannot pick for the customer; once a proposal exists the pick is closed.
    assert put("hq", "voucher").status_code == 403
    with tenant_session(ctx["tid"], app_engine) as s:
        create_proposal(
            s, ctx["tid"], case_id=cid, action=remedy.action, params=remedy.params, reason="t"
        )
    assert put("customer", "voucher").status_code == 409
    assert api.get(f"/cases/{cid}/remedy-options", headers=ctx["customer"]).json()["options"] == []


def test_instant_label_matches_the_real_auto_decision(api, ctx, app_engine):
    voucher = next(o for o in _options(api, ctx).json()["options"] if o["kind"] == "voucher")
    case = _report(api, ctx, remedy_choice=voucher["code"]).json()
    with tenant_session(ctx["tid"], app_engine) as s:
        auto = s.scalar(
            select(Approval.id).where(Approval.proposal_id == uuid.UUID(case["proposal_id"]))
        )
    assert (voucher["approval"] == "instant") == (auto is not None)


def test_instant_is_never_claimed_when_fair_use_would_stop_auto_approval(api, ctx, app_engine):
    with tenant_session(ctx["tid"], app_engine) as s:
        order = s.get(Transaction, ctx["order_id"])
        _, facts = order_facts(s, order.id)
        voucher = next(
            o
            for o in remedy_options(s, order, facts, ctx["multi"])
            if o.remedy.action == "free_item_voucher"
        )
    small = ChoiceOption(
        voucher.code, replace(voucher.remedy, params={**voucher.remedy.params, "value_paise": 1000})
    )
    assert _approval(small, facts, fair_ok=True) == "instant"
    assert _approval(small, facts, fair_ok=False) == "team"


def test_an_unworkable_pick_falls_back_to_the_first_workable_option_and_is_audited(
    ctx, app_engine, monkeypatch
):
    import app.engine.resolver as resolver

    cid = uuid.uuid4()
    real = resolver.order_facts

    def nothing_left(session, tid, **kw):
        order, facts = real(session, tid, **kw)
        return order, replace(facts, refundable_paise=0)  # no refund is possible now

    with tenant_session(ctx["tid"], app_engine) as s:
        s.add(
            Case(
                id=cid,
                tenant_id=ctx["tid"],
                customer_id=ctx["cid"],
                transaction_id=ctx["order_id"],
                category=ctx["multi"],
                status="investigating",
                channel="app",
                opened_at=datetime.now(UTC),
                remedy_choice="refund_50pct",
            )
        )
    monkeypatch.setattr(resolver, "order_facts", nothing_left)
    with tenant_session(ctx["tid"], app_engine) as s:
        case = s.get(Case, cid)
        remedy, proposal_id = propose_for_case(s, SimpleNamespace(tenant_id=ctx["tid"]), case)
        assert remedy.action == "free_item_voucher" and remedy.fallback_from == "refund_50pct"
        assert proposal_id is not None
    with tenant_session(ctx["tid"], app_engine) as s:
        payloads = list(
            s.scalars(
                select(AuditEvent.payload).where(
                    AuditEvent.event == "case.remedy_choice_fallback",
                    AuditEvent.entity_id == cid,
                )
            )
        )
    assert payloads == [{"picked": "refund_50pct", "used": "free_item_voucher"}]


def test_pick_on_another_customers_or_tenants_case_is_404(
    api, ctx, app_engine, maint_engine, seeded_history
):
    other_tid = tenant_id_for(
        next(c.slug for c in seeded_history.values() if tenant_id_for(c.slug) != ctx["tid"])
    )
    made = []
    for tid in (ctx["tid"], other_tid):  # a colleague customer's case, and another tenant's case
        with tenant_session(tid, app_engine) as s:
            q = select(Transaction.id, Transaction.customer_id)
            if tid == ctx["tid"]:
                q = q.where(Transaction.customer_id != ctx["cid"])
            row = s.execute(q.limit(1)).one()
            case_id = uuid.uuid4()
            s.add(
                Case(
                    id=case_id,
                    tenant_id=tid,
                    customer_id=row.customer_id,
                    transaction_id=row.id,
                    category=ctx["multi"],
                    status="investigating",
                    channel="app",
                    opened_at=datetime.now(UTC),
                )
            )
        made.append((tid, case_id))
    try:
        for _, case_id in made:
            resp = api.put(
                f"/cases/{case_id}/remedy-choice",
                headers=ctx["customer"],
                json={"option": "voucher"},
            )
            assert resp.status_code == 404, resp.text
            got = api.get(f"/cases/{case_id}/remedy-options", headers=ctx["customer"])
            assert got.status_code == 404
    finally:
        for tid, case_id in made:
            with tenant_session(tid, maint_engine) as s:
                s.execute(delete(Case).where(Case.id == case_id))


def test_a_pick_without_a_category_in_agents_mode_is_422(api, ctx, app_engine, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_cases.get_settings", lambda: SimpleNamespace(engine_mode="agents")
    )
    resp = api.post(
        "/cases",
        headers=ctx["customer"],
        json={
            "transaction_id": str(ctx["order_id"]),
            "category": None,
            "message": "Wrong thing.",
            "remedy_choice": "refund_50pct",
        },
    )
    assert resp.status_code == 422, resp.text
    with tenant_session(ctx["tid"], app_engine) as s:
        assert s.scalar(select(Case.id).where(Case.transaction_id == ctx["order_id"])) is None


def test_the_refund_option_is_hidden_on_an_order_placed_through_a_delivery_app(
    api, ctx, app_engine, maint_engine
):
    """M1: the delivery app refunds those orders, so only the voucher is offered, a stored
    refund pick falls back to the voucher, and a refund proposal is refused by the same rule."""
    with tenant_session(ctx["tid"], app_engine) as s:
        order = s.get(Transaction, ctx["order_id"])
        original = order.source
        _, facts = order_facts(s, order.id)
        aggregator = facts.settings["aggregator_order_sources"][0]
        order.source = aggregator
    try:
        body = _options(api, ctx).json()
        assert [o["kind"] for o in body["options"]] == ["voucher"]
        assert body["choice_required"] is False
        with tenant_session(ctx["tid"], app_engine) as s:
            order = s.get(Transaction, ctx["order_id"])
            _, facts = order_facts(s, order.id)
            assert facts.settings["refund_channel"] == "aggregator_only"
            assert [o.code for o in remedy_options(s, order, facts, ctx["multi"])] == ["voucher"]
            action = enabled_actions(tenant_pack(s).actions)["refund"]()
            from app.actions.refund import RefundInput

            inp = RefundInput(transaction_id=order.id, amount_paise=100, reason="x")
            assert not action.validate(None, inp, facts).ok
    finally:
        with tenant_session(ctx["tid"], app_engine) as s:
            s.get(Transaction, ctx["order_id"]).source = original
    # Back on an own-channel order the refund request is offered again, voucher first.
    again = _options(api, ctx).json()
    assert [o["kind"] for o in again["options"]] == ["voucher", "refund"]
