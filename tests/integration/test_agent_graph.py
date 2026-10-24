"""The LangGraph case loop with scripted (fake) LLMs, for every tenant (PROJECT.md section 8)."""

import re
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, update

import app.engine.graph as graph
from app.agents.schemas import Clarification, Classification, ResolutionDraft
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Case,
    Customer,
    LineItem,
    RefundOperation,
    Ticket,
    TicketMessage,
    Transaction,
    User,
    WorkflowRun,
)
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import tenant_dirs
from app.llm.providers import BudgetExceeded
from app.rag.embeddings import HashEmbedder
from app.rag.ingest import ingest_policies
from app.rag.retrieve import PolicyFindings

EMBEDDER = HashEmbedder()
NOW = datetime.now(UTC)
REF = re.compile(r'ref="([^"]+)"')


class FakeLLM:
    """Scripted structured replies per schema; a reply may be a callable(messages)."""

    def __init__(self, script: dict):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, list]] = []

    def invoke_structured(self, messages, schema):
        self.calls.append((schema.__name__, messages))
        reply = self.script[schema.__name__].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply(messages) if callable(reply) else reply


class FakeBudget:
    def __init__(self, llms):
        self.llms = llms

    def snapshot(self):
        return {"calls": sum(len(llm.calls) for llm in self.llms)}


@pytest.fixture(scope="session")
def policies_loaded(app_engine, seeded_history):
    for folder in tenant_dirs():
        ingest_policies(app_engine, seeded_history[folder.name].slug, folder, EMBEDDER)
    return seeded_history


@pytest.fixture
def case(app_engine, maint_engine, policies_loaded, tenant):
    """A free-text case (no category) on a demo customer's order with one item missing."""
    cfg = policies_loaded[tenant.name]
    tid = tenant_id_for(cfg.slug)
    email = next(u.email for u in cfg.users if u.role == "customer")
    with tenant_session(tid, app_engine) as s:
        uid = s.scalar(select(User.id).where(User.email == email))
        cust = s.scalar(select(Customer.id).where(Customer.user_id == uid))
        order = s.scalars(
            select(Transaction)
            .where(Transaction.customer_id == cust)
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
        line = s.scalars(
            select(LineItem)
            .where(LineItem.transaction_id == order.id)
            .order_by(LineItem.unit_price_paise.desc())
            .limit(1)
        ).one()
        other = s.scalar(select(Transaction.id).where(Transaction.customer_id != cust).limit(1))
        s.execute(
            update(LineItem)
            .where(LineItem.id == line.id)
            .values(quantity_fulfilled=line.quantity - 1)
        )
        case_id = uuid.uuid4()
        s.add(
            Case(
                id=case_id,
                tenant_id=tid,
                customer_id=cust,
                transaction_id=order.id,
                category=None,
                status="investigating",
                channel="app",
                opened_at=NOW,
            )
        )
        s.flush()
        s.add(
            Ticket(
                tenant_id=tid,
                customer_id=cust,
                transaction_id=order.id,
                case_id=case_id,
                category="unknown",
                status="open",
                channel="app",
                opened_at=NOW,
            )
        )
        info = {
            "tid": tid,
            "case_id": case_id,
            "order_id": order.id,
            "other_order": other,
            "missing": line.unit_price_paise,
            "line_id": line.id,
            "qty": line.quantity,
        }
    yield info
    with tenant_session(tid, app_engine) as s:
        s.execute(
            update(LineItem)
            .where(LineItem.id == info["line_id"])
            .values(quantity_fulfilled=info["qty"])
        )
    with tenant_session(tid, maint_engine) as s:
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id == case_id))
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid, RefundOperation.transaction_id == order.id
            )
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id == case_id))


def _refund(case, amount=None, cite=True, order=None):
    def reply(messages):
        refs = REF.findall(messages[1].content)
        return ResolutionDraft(
            action="refund",
            params={
                "transaction_id": str(order or case["order_id"]),
                "amount_paise": amount or case["missing"],
                "reason": "missing item",
            },
            reason="item missing from the order",
            citations=refs[:1] if cite else ["made_up_v9#1"],
        )

    return reply


def _run(app_engine, case, classifier, resolver):
    deps = graph.Deps(app_engine, classifier, resolver, EMBEDDER, now=NOW)
    return graph.run_case(
        deps,
        case["tid"],
        case["case_id"],
        "One item was missing from my order.",
        FakeBudget([classifier, resolver]),
    )


def _classify(category="missing_items", needs=()):
    return Classification(category=category, confidence=0.9, needs_info=list(needs))


def _case(app_engine, case):
    with tenant_session(case["tid"], app_engine) as s:
        c = s.get(Case, case["case_id"])
        return c.status, s.scalars(
            select(ActionProposal).where(ActionProposal.case_id == c.id)
        ).all()


def test_happy_path_ends_in_a_cited_validated_proposal(app_engine, case):
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "proposed", out
    status, proposals = _case(app_engine, case)
    assert status == "awaiting_approval"  # refunds are never auto-approved
    (p,) = proposals
    assert p.action == "refund" and p.amount_paise == case["missing"]
    assert p.citations and p.citations[0]["section_ref"]
    with tenant_session(case["tid"], app_engine) as s:
        run = s.get(WorkflowRun, uuid.UUID(out["run_id"]))
        assert (run.status, run.llm_calls) == ("completed", 2)
        assert p.run_id == run.id


@pytest.mark.parametrize(
    "classification", [_classify(needs=["which item"]), _classify(category="not_a_category")]
)
def test_missing_info_asks_one_question_and_pauses(app_engine, case, classification):
    clf = FakeLLM(
        {
            "Classification": [classification],
            "Clarification": [Clarification(question="Which item was missing?")],
        }
    )
    res = FakeLLM({"ResolutionDraft": []})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "awaiting_info" and res.calls == []
    status, proposals = _case(app_engine, case)
    assert status == "awaiting_info" and proposals == []
    with tenant_session(case["tid"], app_engine) as s:
        bodies = s.scalars(
            select(TicketMessage.body)
            .join(Ticket)
            .where(Ticket.case_id == case["case_id"], TicketMessage.author == "system")
        )
        assert "Which item was missing?" in list(bodies)


def test_one_repair_then_a_valid_proposal(app_engine, case):
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case, amount=10**9), _refund(case)]})
    assert _run(app_engine, case, clf, res)["outcome"] == "proposed"
    assert len(res.calls) == 2
    assert "Code rejected your previous proposal" in res.calls[1][1][-1].content


@pytest.mark.parametrize(
    "drafts",
    [
        lambda c: [_refund(c, amount=10**9), _refund(c, amount=10**9)],  # over limits twice
        lambda c: [_refund(c, cite=False), _refund(c, cite=False)],
    ],  # invents citations twice
    ids=["over_limit", "invented_citation"],
)
def test_rejected_twice_escalates_without_a_proposal(app_engine, case, drafts):
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": drafts(case)})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "escalated"
    status, proposals = _case(app_engine, case)
    assert status == "escalated" and proposals == []


def test_a_forged_order_id_from_the_model_grants_nothing(app_engine, case):
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case, amount=100, order=case["other_order"])] * 2})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "escalated"
    assert _case(app_engine, case)[1] == []


def test_model_choosing_escalate_or_none_is_respected(app_engine, case):
    for action, expected in (("escalate", "escalated"), ("none", "resolved")):
        clf = FakeLLM({"Classification": [_classify()]})
        res = FakeLLM({"ResolutionDraft": [ResolutionDraft(action=action, reason="because")]})
        _run(app_engine, case, clf, res)
        assert _case(app_engine, case)[0] == expected


def test_no_policy_in_effect_escalates(app_engine, case, monkeypatch):
    monkeypatch.setattr(
        graph, "search_policies", lambda *a, **k: PolicyFindings(citations=[], missing=True)
    )
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": []})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "escalated" and res.calls == []


def test_llm_budget_exceeded_escalates(app_engine, case):
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [BudgetExceeded("8 calls")]})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "escalated"
    with tenant_session(case["tid"], app_engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(WorkflowRun)
                .where(WorkflowRun.case_id == case["case_id"], WorkflowRun.status == "escalated")
            )
            == 1
        )
