"""Fair-use signal (E2.5), for every tenant: at `fair_use_max_grants_30d` refunds/vouchers
approved for a customer in 30 days, nothing more is auto-approved; the case waits for a
person (never an automatic denial) and the approvals list shows the count."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

import app.engine.graph as graph
from app.agents.schemas import Classification, ResolutionDraft
from app.core.db import tenant_session
from app.core.models import Approval, Case, Customer, Ticket, Transaction, User
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import load_context, tenant_id_for
from app.core.tenant_config import tenant_dirs
from app.engine.approvals import decide
from app.engine.eligibility import fair_use, order_facts
from app.engine.proposals import create_proposal
from app.rag.ingest import ingest_policies
from tests.helpers import login
from tests.integration.test_agent_graph import EMBEDDER, REF, FakeBudget, FakeLLM

NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def policies_ready(app_engine, seeded_history):
    for folder in tenant_dirs():
        ingest_policies(app_engine, seeded_history[folder.name].slug, folder, EMBEDDER)
    return seeded_history


@pytest.fixture
def world(app_engine, maint_engine, policies_ready, tenant):
    """The demo customer's latest order, the pack's voucher category, and cleanup of every
    case this test creates on that order (proposals and approvals cascade)."""
    cfg = policies_ready[tenant.name]
    tid = tenant_id_for(cfg.slug)
    customer = next(u for u in cfg.users if u.role == "customer")
    hq_email = next(u.email for u in cfg.users if u.role == "hq_owner")
    with tenant_session(tid, app_engine) as s:
        uid = s.scalar(select(User.id).where(User.email == customer.email))
        cust = s.scalar(select(Customer.id).where(Customer.user_id == uid))
        order = s.scalars(
            select(Transaction)
            .where(Transaction.customer_id == cust)
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
        order_id = order.id
        pack = tenant_pack(s)
        _, facts = order_facts(s, order_id)
        hq = load_context(s, tid, s.scalar(select(User.id).where(User.email == hq_email)))
    voucher_category = next(c for c, rule in pack.remedies.items() if rule == "voucher")
    info = {
        "tid": tid,
        "cfg": cfg,
        "customer_id": cust,
        "customer_email": customer.email,
        "order_id": order_id,
        "category": voucher_category,
        "max": facts.settings["fair_use_max_grants_30d"],
        "voucher_paise": min(
            facts.settings["voucher_auto_approve_max_paise"], facts.settings["voucher_max_paise"]
        ),
        "hq": hq,
    }
    yield info
    with tenant_session(tid, maint_engine) as s:
        case_ids = select(Case.id).where(Case.tenant_id == tid, Case.transaction_id == order_id)
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(case_ids)))
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.transaction_id == order_id))


def _count(app_engine, w) -> int:
    with tenant_session(w["tid"], app_engine) as s:
        _, facts = order_facts(s, w["order_id"])
        return fair_use(s, w["customer_id"], facts.settings, NOW).grants_30d


def _grant(app_engine, w, *, n=1, days_ago=1, action="free_item_voucher", decision="approved"):
    """n past decisions for this customer: a closed case, a proposal and its approval."""
    params = {"transaction_id": str(w["order_id"]), "reason": "earlier case"}
    params |= {"amount_paise": 100} if action == "refund" else {"value_paise": 100}
    with tenant_session(w["tid"], app_engine) as s:
        for _ in range(n):
            case = Case(
                id=uuid.uuid4(),
                tenant_id=w["tid"],
                customer_id=w["customer_id"],
                transaction_id=w["order_id"],
                category=w["category"],
                status="resolved",
                channel="app",
                opened_at=NOW - timedelta(days=days_ago),
            )
            s.add(case)
            s.flush()
            p = create_proposal(
                s, w["tid"], case_id=case.id, action=action, params=params, reason="earlier"
            )
            decided = NOW - timedelta(days=days_ago)
            s.add(
                Approval(
                    id=uuid.uuid4(),
                    tenant_id=w["tid"],
                    proposal_id=p.id,
                    payload_hash=p.payload_hash,
                    decision=decision,
                    mode="human",
                    decided_by=w["hq"].user_id,
                    decided_at=decided,
                    expires_at=decided + timedelta(hours=1),
                )
            )


def _fill_to(app_engine, w, target):
    have = _count(app_engine, w)
    if have > target:
        pytest.skip("leftover grants for this customer are already above the target")
    if target > have:
        _grant(app_engine, w, n=target - have)
    assert _count(app_engine, w) == target


def _open(api, w):
    headers = login(api, w["cfg"].slug, w["customer_email"])
    resp = api.post(
        "/cases",
        headers=headers,
        json={"transaction_id": str(w["order_id"]), "category": w["category"], "message": "x"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _status_and_approval(app_engine, w, case_id, proposal_id):
    with tenant_session(w["tid"], app_engine) as s:
        status = s.get(Case, uuid.UUID(str(case_id))).status
        approval = s.scalar(
            select(Approval).where(Approval.proposal_id == uuid.UUID(str(proposal_id)))
        )
        return status, approval and (approval.decision, approval.mode)


def test_below_the_threshold_a_voucher_is_still_auto_approved(api, app_engine, world):
    w = world
    _fill_to(app_engine, w, w["max"] - 1)
    opened = _open(api, w)
    assert opened["action"] == "free_item_voucher"
    status, approval = _status_and_approval(app_engine, w, opened["id"], opened["proposal_id"])
    assert (status, approval) == ("executing", ("approved", "auto"))


def test_at_the_threshold_a_person_decides_and_sees_the_count(api, app_engine, world):
    w = world
    _fill_to(app_engine, w, w["max"])
    opened = _open(api, w)
    status, approval = _status_and_approval(app_engine, w, opened["id"], opened["proposal_id"])
    assert (status, approval) == ("awaiting_approval", None)  # not approved, not denied

    hq = login(api, w["cfg"].slug, next(u.email for u in w["cfg"].users if u.role == "hq_owner"))
    item = next(p for p in api.get("/approvals", headers=hq).json() if p["case_id"] == opened["id"])
    assert item["checks"]["fair_use_ok"] is False
    assert item["checks"]["fair_use_grants_30d"] == w["max"]
    assert item["eligible"] and item["errors"] == []  # a signal, never a reason to refuse

    with tenant_session(w["tid"], app_engine) as s:  # and a person can still approve it
        a = decide(s, w["hq"], uuid.UUID(opened["proposal_id"]), "approved", datetime.now(UTC))
        assert a.decision == "approved" and a.mode == "human"


def test_refunds_count_but_old_and_rejected_decisions_do_not(app_engine, world):
    w = world
    base = _count(app_engine, w)
    _grant(app_engine, w, action="refund")
    _grant(app_engine, w, days_ago=31)
    _grant(app_engine, w, decision="rejected")
    assert _count(app_engine, w) == base + 1


def _agent_case(app_engine, w) -> uuid.UUID:
    case_id = uuid.uuid4()
    with tenant_session(w["tid"], app_engine) as s:
        s.add(
            Case(
                id=case_id,
                tenant_id=w["tid"],
                customer_id=w["customer_id"],
                transaction_id=w["order_id"],
                category=None,
                status="investigating",
                channel="app",
                opened_at=NOW,
            )
        )
        s.flush()
        s.add(
            Ticket(
                tenant_id=w["tid"],
                customer_id=w["customer_id"],
                transaction_id=w["order_id"],
                case_id=case_id,
                category="unknown",
                status="open",
                channel="app",
                opened_at=NOW,
            )
        )
    return case_id


def _run_agents(app_engine, w, case_id):
    def voucher(messages):
        return ResolutionDraft(
            action="free_item_voucher",
            params={
                "transaction_id": str(w["order_id"]),
                "value_paise": w["voucher_paise"],
                "reason": "problem with the order",
            },
            reason="problem with the order",
            citations=REF.findall(messages[1].content)[:1],
        )

    clf = FakeLLM({"Classification": [Classification(category=w["category"], confidence=0.9)]})
    res = FakeLLM({"ResolutionDraft": [voucher]})
    deps = graph.Deps(app_engine, clf, res, EMBEDDER, now=NOW)
    return graph.run_case(deps, w["tid"], case_id, "My order was wrong.", FakeBudget([clf, res]))


@pytest.mark.parametrize("at_threshold", [False, True], ids=["below", "at"])
def test_agent_path_applies_the_same_rule(app_engine, world, at_threshold):
    w = world
    _fill_to(app_engine, w, w["max"] if at_threshold else w["max"] - 1)
    case_id = _agent_case(app_engine, w)
    out = _run_agents(app_engine, w, case_id)
    # Below the threshold the graph continues past approve (auto); at it, the run pauses.
    assert out["outcome"] == ("proposed" if at_threshold else "approved"), out
    status, approval = _status_and_approval(app_engine, w, case_id, out["proposal_id"])
    if at_threshold:
        assert (status, approval) == ("awaiting_approval", None)
    else:
        assert (status, approval) == ("executing", ("approved", "auto"))
