"""The LangGraph case loop with scripted (fake) LLMs, for every tenant (PROJECT.md section 8)."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select, update

import app.engine.graph as graph
from app.agents.schemas import BaselineDecision, Classification, ResolutionDraft
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
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import tenant_dirs
from app.engine.baseline import build_baseline_graph
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
                RefundOperation.tenant_id == tid,
                RefundOperation.transaction_id == info["order_id"],
            )
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id == case_id))


def _refund(case, amount=None, cite=True, order=None, citations=None):
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
            citations=citations if citations is not None else (refs[:1] if cite else ["x#9"]),
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
        rows = s.scalars(select(ActionProposal).where(ActionProposal.case_id == c.id)).all()
        return c.status, [
            SimpleNamespace(action=p.action, amount_paise=p.amount_paise, citations=p.citations,
                            run_id=p.run_id)
            for p in rows
        ]  # fmt: skip


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
        # Paused at the approve node (interrupt), waiting for a person's decision.
        assert (run.status, run.llm_calls) == ("paused", 2) and out["paused"]
        assert p.run_id == run.id


@pytest.mark.parametrize(
    "classification",
    [
        _classify(needs=["which item"]),
        _classify(category="not_a_category"),
        Classification(category="missing_items", confidence=0.2),
    ],
    ids=["needs_info", "unknown_category", "low_confidence"],
)
def test_missing_info_asks_one_question_and_pauses(app_engine, case, classification):
    clf = FakeLLM({"Classification": [classification]})
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
        assert list(bodies) == [graph.QUESTIONS[graph.NEED_DETAILS]]  # code's text, not a model's
    assert len(clf.calls) == 1


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
        lambda c: [_refund(c, cite=False), _refund(c, cite=False)],  # invents citations
        lambda c: [_refund(c, citations=[]), _refund(c, citations=[])],  # cites nothing
    ],
    ids=["over_limit", "invented_citation", "no_citation"],
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


@pytest.mark.parametrize("action", ["escalate", "none"])
def test_escalate_or_none_goes_to_a_person(app_engine, case, action):
    """An LLM never closes a case: "no compensation" is a suggestion a person confirms."""
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [ResolutionDraft(action=action, reason="because")]})
    _run(app_engine, case, clf, res)
    assert _case(app_engine, case) == ("escalated", [])


def test_a_forged_order_id_gets_one_repair(app_engine, case):
    clf = FakeLLM({"Classification": [_classify()]})
    forged = _refund(case, amount=100, order=case["other_order"])
    res = FakeLLM({"ResolutionDraft": [forged, _refund(case)]})
    assert _run(app_engine, case, clf, res)["outcome"] == "proposed"
    assert str(case["other_order"]) not in res.calls[1][1][-1].content  # never echoed back


def test_any_error_escalates_instead_of_leaving_the_case_open(app_engine, case):
    clf = FakeLLM({"Classification": [RuntimeError("boom")]})
    out = _run(app_engine, case, clf, FakeLLM({}))
    assert out["outcome"] == "escalated" and "RuntimeError" in out["reason"]
    assert _case(app_engine, case)[0] == "escalated"


def test_a_case_is_worked_by_one_run_only(app_engine, case):
    clf = FakeLLM({"Classification": [_classify()] * 2})
    res = FakeLLM({"ResolutionDraft": [_refund(case)] * 2})
    assert _run(app_engine, case, clf, res)["outcome"] == "proposed"
    assert _run(app_engine, case, clf, res)["outcome"] == "skipped"  # e.g. a resubmitted report
    assert len(_case(app_engine, case)[1]) == 1


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


@pytest.mark.parametrize("age_minutes, outcome", [(1, "skipped"), (60, "proposed")])
def test_a_crashed_run_only_blocks_the_case_until_its_ttl(app_engine, case, age_minutes, outcome):
    with tenant_session(case["tid"], app_engine) as s:
        started = datetime.now(UTC) - timedelta(minutes=age_minutes)  # at test time, not import
        s.add(WorkflowRun(tenant_id=case["tid"], case_id=case["case_id"], status="running",
                          created_at=started))  # fmt: skip
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    assert _run(app_engine, case, clf, res)["outcome"] == outcome


def _ceiling(app_engine, case):
    """The rule's remedy for this case's (missing-item) order, under the pack's own category."""
    with tenant_session(case["tid"], app_engine) as s:
        remedies = tenant_pack(s).remedies
        category = next(cat for cat, rule in remedies.items() if rule == "refund_missing")
        c = s.get(Case, case["case_id"])
        c.category = category
        s.flush()
        ceiling = graph.decide_remedy(s, c)
    assert ceiling.action == "refund", ceiling
    return category, ceiling


def test_proposals_never_exceed_the_business_rule(app_engine, case):
    """Policy text or an injected message can't buy more than the tenant's configured rule."""
    category, ceiling = _ceiling(app_engine, case)
    over = ceiling.params["amount_paise"] + 1
    clf = FakeLLM({"Classification": [_classify(category)]})
    res = FakeLLM({"ResolutionDraft": [_refund(case, amount=over)] * 2})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "escalated" and "business rules allow" in out["reason"]
    assert _case(app_engine, case)[1] == []


def test_only_the_rules_action_can_be_proposed(app_engine, case):
    other = ResolutionDraft(
        action="free_item_voucher",
        params={"transaction_id": str(case["order_id"]), "value_paise": 100, "reason": "x"},
        reason="voucher instead",
        citations=["any"],
    )
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [other, other]})
    assert _run(app_engine, case, clf, res)["outcome"] == "escalated"
    assert _case(app_engine, case)[1] == []


def test_no_automatic_remedy_escalates_without_asking_the_model(app_engine, case, monkeypatch):
    monkeypatch.setattr(graph, "decide_remedy", lambda s, c: graph.Remedy(None, {}, "no rule",
                                                                          "escalate"))  # fmt: skip
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": []})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "escalated" and res.calls == []


def test_a_draft_at_the_ceiling_is_accepted(app_engine, case):
    category, ceiling = _ceiling(app_engine, case)
    clf = FakeLLM({"Classification": [_classify(category)]})
    res = FakeLLM({"ResolutionDraft": [_refund(case, amount=ceiling.params["amount_paise"])]})
    assert _run(app_engine, case, clf, res)["outcome"] == "proposed"


@pytest.mark.parametrize("amount", ["999999", 999999.0, 10.5])
def test_non_integer_amounts_never_crash_or_pass_the_ceiling(app_engine, case, amount):
    category, _ = _ceiling(app_engine, case)
    clf = FakeLLM({"Classification": [_classify(category)]})
    res = FakeLLM({"ResolutionDraft": [_refund(case, amount=amount)] * 2})
    out = _run(app_engine, case, clf, res)
    assert out["outcome"] == "escalated" and "internal error" not in out["reason"]
    assert _case(app_engine, case)[1] == []


# --- Single-call baseline (evals' comparison point): same checks, one LLM call ----------


def _pack_categories(app_engine, case):
    with tenant_session(case["tid"], app_engine) as s:
        pack = tenant_pack(s)
        missing = next(c for c, rule in pack.remedies.items() if rule == "refund_missing")
        no_rule = next(c for c in pack.issue_categories if c not in pack.remedies)
    return missing, no_rule


def _decision(case, category, amount=None, action="refund", confidence=0.9):
    def reply(messages):
        refs = REF.findall(messages[1].content)
        return BaselineDecision(
            category=category,
            confidence=confidence,
            action=action,
            params={"transaction_id": str(case["order_id"]),
                    "amount_paise": amount or case["missing"], "reason": "missing item"},
            reason="item missing from the order",
            citations=refs[:1],
        )  # fmt: skip

    return reply


def _run_baseline(app_engine, case, resolver):
    deps = graph.Deps(app_engine, FakeLLM({}), resolver, EMBEDDER, now=NOW)
    return graph.run_case(deps, case["tid"], case["case_id"], "One item was missing.",
                          FakeBudget([resolver]), build_baseline_graph)  # fmt: skip


def test_baseline_classifies_and_proposes_in_one_call(app_engine, case):
    missing, _ = _pack_categories(app_engine, case)
    res = FakeLLM({"BaselineDecision": [_decision(case, missing)]})
    out = _run_baseline(app_engine, case, res)
    assert out["outcome"] == "proposed", out
    assert len(res.calls) == 1
    status, (p,) = _case(app_engine, case)
    assert status == "awaiting_approval" and p.amount_paise == case["missing"]
    with tenant_session(case["tid"], app_engine) as s:
        assert s.get(Case, case["case_id"]).category == missing


def test_baseline_over_the_rule_escalates_without_a_repair(app_engine, case):
    missing, _ = _pack_categories(app_engine, case)
    res = FakeLLM({"BaselineDecision": [_decision(case, missing, amount=10**9)]})
    out = _run_baseline(app_engine, case, res)
    assert out["outcome"] == "escalated" and len(res.calls) == 1
    assert _case(app_engine, case) == ("escalated", [])


def test_baseline_category_without_a_rule_escalates(app_engine, case):
    _, no_rule = _pack_categories(app_engine, case)
    res = FakeLLM({"BaselineDecision": [_decision(case, no_rule)]})
    assert _run_baseline(app_engine, case, res)["outcome"] == "escalated"
    assert _case(app_engine, case) == ("escalated", [])


@pytest.mark.parametrize("category, confidence", [("not_a_category", 0.9), (None, 0.1)])
def test_baseline_unsure_asks_the_customer(app_engine, case, category, confidence):
    missing, _ = _pack_categories(app_engine, case)
    res = FakeLLM({"BaselineDecision": [_decision(case, category or missing,
                                                  confidence=confidence)]})  # fmt: skip
    assert _run_baseline(app_engine, case, res)["outcome"] == "awaiting_info"
    assert _case(app_engine, case) == ("awaiting_info", [])
