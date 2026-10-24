"""The case loop as a LangGraph graph (PROJECT.md section 8): classify -> investigate ->
policy -> resolve -> propose, stopping before approval (approval pause/resume is E4.1).

Routing: missing info -> one clarification question, pause; no policy -> escalate; invalid
model output or a proposal code rejects -> one repair attempt, then escalate; more than
MAX_STEPS steps or the LLM call budget -> escalate.

Every node opens its own short tenant transaction; no transaction is open during an LLM call
(hard rule 5 applies to any network call). Agents only read: the proposal is created by code
(create_proposal), after strict param validation, case binding and eligibility.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import Engine, select

from app.actions.base import Facts, enabled_actions, get_action
from app.agents import tools
from app.agents.prompts import clarification_messages, classifier_messages, resolution_messages
from app.agents.schemas import Clarification, Classification, ResolutionDraft
from app.core import audit
from app.core.db import tenant_session
from app.core.models import Case, Ticket, TicketMessage, WorkflowRun
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.engine.approvals import auto_decide
from app.engine.eligibility import order_facts
from app.engine.proposals import ProposalError, create_proposal
from app.llm.providers import LLMError
from app.rag.retrieve import search_policies

MAX_STEPS = 12
POLICY_K = 6


class StructuredLLM(Protocol):
    def invoke_structured(self, messages, schema): ...


@dataclass
class Deps:
    engine: Engine
    classifier: StructuredLLM
    resolver: StructuredLLM
    embedder: Any  # app.rag.embeddings.Embedder
    now: datetime | None = None


class CaseState(TypedDict, total=False):
    tenant_id: str
    case_id: str
    run_id: str
    message: str
    category: str | None
    needs_info: list[str]
    evidence: dict | None
    citations: list[dict]
    draft: dict
    proposal_id: str | None
    outcome: str  # proposed | awaiting_info | escalated | no_action
    reason: str
    errors: list[str]
    step_count: int


def _ctx(state: CaseState) -> TenantContext:
    """System context for the run: tenant only. Never used for scope/role decisions."""
    tid = uuid.UUID(state["tenant_id"])
    return TenantContext(tid, uuid.UUID(int=0), uuid.UUID(int=0), "hq_owner", frozenset(),
                         frozenset())  # fmt: skip


def _step(state: CaseState) -> int:
    return state.get("step_count", 0) + 1


def build_graph(deps: Deps):
    def classify(state: CaseState) -> CaseState:
        step = _step(state)
        with tenant_session(uuid.UUID(state["tenant_id"]), deps.engine) as s:
            case = s.get(Case, uuid.UUID(state["case_id"]))
            pack = tenant_pack(s)
            categories, vocabulary = list(pack.issue_categories), dict(pack.vocabulary)
            known = case.category
        if known:  # the customer already chose a category (form): no LLM call needed
            return {"category": known, "needs_info": [], "step_count": step}
        result: Classification = deps.classifier.invoke_structured(
            classifier_messages(state["message"], categories, vocabulary), Classification
        )
        if result.category not in categories:
            return {"category": None, "needs_info": ["what went wrong with the order"],
                    "step_count": step}  # fmt: skip
        return {"category": result.category, "needs_info": result.needs_info,
                "step_count": step}  # fmt: skip

    def investigate(state: CaseState) -> CaseState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        with tenant_session(tid, deps.engine) as s:
            case = s.get(Case, uuid.UUID(state["case_id"]))
            scope = tools.Scope(tid, case.id, case.customer_id)
            if case.transaction_id is None:
                return {"needs_info": ["which order this is about"], "step_count": step}
            order_ref = str(case.transaction_id)
            order = tools.get_transaction(s, scope, order_ref)
            if not order["ok"]:
                return {"needs_info": ["which order this is about"], "step_count": step}
            _, facts = order_facts(s, case.transaction_id)
            evidence = {
                "order": order["data"],
                "fulfilment": tools.get_fulfilment(s, scope, order_ref),
                "payments": tools.get_payment(s, scope, order_ref),
                "customer": tools.get_customer(s, scope),
                "previous_cases": tools.get_case_history(s, scope),
                "refundable_paise": facts.refundable_paise,
                "missing_items_value_paise": sum(
                    i["unit_price_paise"] * (i["quantity"] - i["quantity_fulfilled"])
                    for i in order["data"]["items"]
                ),
            }
        return {"evidence": evidence, "step_count": step}

    def policy(state: CaseState) -> CaseState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        order = state["evidence"]["order"]
        query = f"{state['category'].replace('_', ' ')}: {state['message']}"
        with tenant_session(tid, deps.engine) as s:
            findings = search_policies(
                s,
                deps.embedder,
                query,
                as_of=datetime.fromisoformat(order["placed_at"]).date(),  # judged by order date
                brand_id=uuid.UUID(order["brand_id"]),
                location_id=uuid.UUID(order["location_id"]),
                k=POLICY_K,
            )
        citations = [
            {"section_ref": c.section_ref, "version": c.version, "scope": c.scope,
             "heading": c.heading, "text": c.text, "doc_key": c.doc_key, "topic": c.topic}
            for c in findings.citations
        ]  # fmt: skip
        update: CaseState = {"citations": citations, "step_count": step}
        if findings.missing:
            update.update(outcome="escalated", reason="no policy in effect covers this case")
        elif findings.conflicts:
            update.update(outcome="escalated", reason="conflicting policies: "
                          + "; ".join(findings.conflicts))  # fmt: skip
        return update

    def resolve(state: CaseState) -> CaseState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        with tenant_session(tid, deps.engine) as s:
            actions = enabled_actions(tenant_pack(s).actions)
            order_id = uuid.UUID(state["evidence"]["order"]["transaction_id"])
            _, facts = order_facts(s, order_id)
        schemas = {name: cls.Input.model_json_schema() for name, cls in actions.items()}
        allowed_refs = {c["section_ref"] for c in state["citations"]}
        errors: list[str] = []
        for _attempt in range(2):  # the draft, plus one repair if code rejects it
            draft: ResolutionDraft = deps.resolver.invoke_structured(
                resolution_messages(state["message"], state["category"], state["evidence"],
                                    state["citations"], schemas, errors or None),
                ResolutionDraft,
            )  # fmt: skip
            if draft.action in ("none", "escalate"):
                return {"outcome": "no_action" if draft.action == "none" else "escalated",
                        "reason": draft.reason, "step_count": step}  # fmt: skip
            errors = _check_draft(draft, actions, facts, allowed_refs)
            if not errors:
                return {"proposal_id": None, "reason": draft.reason, "step_count": step,
                        "errors": [], "draft": draft.model_dump()}  # fmt: skip
        return {"outcome": "escalated", "reason": "proposal rejected by code: "
                + "; ".join(errors), "step_count": step}  # fmt: skip

    def propose(state: CaseState) -> CaseState:
        step = _step(state)
        draft = ResolutionDraft.model_validate(state["draft"])
        tid = uuid.UUID(state["tenant_id"])
        now = deps.now or datetime.now(UTC)
        citations = [c for c in state["citations"] if c["section_ref"] in set(draft.citations)]
        try:
            with tenant_session(tid, deps.engine) as s:
                proposal = create_proposal(
                    s, _ctx(state), case_id=uuid.UUID(state["case_id"]), action=draft.action,
                    params=draft.params, reason=draft.reason,
                    citations=[{"section_ref": c["section_ref"], "doc_key": c["doc_key"],
                                "version": c["version"]} for c in citations],
                    run_id=uuid.UUID(state["run_id"]),
                )  # fmt: skip
                approval = auto_decide(s, tid, proposal.id, now)
                case = s.get(Case, uuid.UUID(state["case_id"]))
                case.status = "executing" if approval is not None else "awaiting_approval"
                proposal_id = str(proposal.id)
        except ProposalError as exc:  # e.g. an order id that isn't this case's
            return {"outcome": "escalated", "reason": f"proposal refused: {exc}",
                    "step_count": step}  # fmt: skip
        return {"outcome": "proposed", "proposal_id": proposal_id, "step_count": step}

    def ask(state: CaseState) -> CaseState:
        step = _step(state)
        question = deps.classifier.invoke_structured(
            clarification_messages(state["message"], state.get("needs_info") or []), Clarification
        ).question
        _finish(deps, state, "awaiting_info", question, ticket_text=question)
        return {"outcome": "awaiting_info", "reason": question, "step_count": step}

    def escalate(state: CaseState) -> CaseState:
        reason = state.get("reason") or (
            "step limit reached" if state.get("step_count", 0) >= MAX_STEPS else "needs a person"
        )
        _finish(deps, state, "escalated", reason)
        return {"outcome": "escalated", "step_count": _step(state)}

    def no_action(state: CaseState) -> CaseState:
        _finish(deps, state, "resolved", state.get("reason", "no compensation applies"))
        return {"outcome": "no_action", "step_count": _step(state)}

    def route_after(node: str):
        def route(state: CaseState) -> str:
            if state.get("step_count", 0) >= MAX_STEPS:
                return "escalate"
            if state.get("outcome") == "escalated":
                return "escalate"
            if state.get("outcome") == "no_action":
                return "no_action"
            if node in ("classify", "investigate") and state.get("needs_info"):
                return "ask"
            return {"classify": "investigate", "investigate": "policy", "policy": "resolve",
                    "resolve": "propose"}[node]  # fmt: skip

        return route

    g = StateGraph(CaseState)
    for name, fn in [("classify", classify), ("investigate", investigate), ("policy", policy),
                     ("resolve", resolve), ("propose", propose), ("ask", ask),
                     ("escalate", escalate), ("no_action", no_action)]:  # fmt: skip
        g.add_node(name, fn)
    g.set_entry_point("classify")
    for node in ("classify", "investigate", "policy", "resolve"):
        g.add_conditional_edges(node, route_after(node))
    for terminal in ("propose", "ask", "escalate", "no_action"):
        g.add_edge(terminal, END)
    return g.compile()


def _check_draft(draft: ResolutionDraft, actions: dict, facts: Facts, allowed: set[str]) -> list:
    """Code's checks on a draft before anything is stored: known action, strict params,
    deterministic eligibility, citations only from what retrieval returned."""
    if draft.action not in actions:
        return [f"action {draft.action!r} is not available"]
    action = get_action(draft.action)()
    try:
        inp = action.Input.model_validate_json(json.dumps(draft.params))
    except Exception as exc:  # pydantic ValidationError or bad JSON types
        return [f"params invalid: {str(exc)[:200]}"]
    result = action.validate(None, inp, facts)
    errors = list(result.errors)
    unknown = [ref for ref in draft.citations if ref not in allowed]
    if unknown:
        errors.append(f"cited refs that were not provided: {unknown}")
    return errors


def _finish(deps: Deps, state: CaseState, status: str, reason: str, ticket_text: str = "") -> None:
    tid = uuid.UUID(state["tenant_id"])
    now = deps.now or datetime.now(UTC)
    with tenant_session(tid, deps.engine) as s:
        case = s.get(Case, uuid.UUID(state["case_id"]))
        case.status = status
        if ticket_text:
            ticket_id = s.scalar(select(Ticket.id).where(Ticket.case_id == case.id))
            if ticket_id is not None:
                s.add(TicketMessage(tenant_id=tid, ticket_id=ticket_id, author="system",
                                    body=ticket_text, sent_at=now))  # fmt: skip
        audit.record(s, tid, actor_type="agent", actor_id=None, event=f"case.{status}",
                     entity_type="case", entity_id=case.id,
                     payload={"reason": reason})  # fmt: skip


def run_case(deps: Deps, tenant_id: uuid.UUID, case_id: uuid.UUID, message: str, budget) -> dict:
    """Run the graph for one case. Records a workflow_runs row with the step/LLM counters.
    Any LLM failure (budget exceeded, rate limited everywhere, invalid output after repair)
    escalates the case instead of guessing."""
    run_id = uuid.uuid4()
    with tenant_session(tenant_id, deps.engine) as s:
        s.add(WorkflowRun(id=run_id, tenant_id=tenant_id, case_id=case_id, status="running"))
    state: CaseState = {"tenant_id": str(tenant_id), "case_id": str(case_id),
                        "run_id": str(run_id), "message": message, "step_count": 0}  # fmt: skip
    try:
        final = build_graph(deps).invoke(state, {"recursion_limit": MAX_STEPS + 4})
    except LLMError as exc:
        final = {**state, "outcome": "escalated", "reason": f"LLM: {type(exc).__name__}"}
        _finish(deps, final, "escalated", final["reason"])
    snapshot = budget.snapshot()
    with tenant_session(tenant_id, deps.engine) as s:
        run = s.get(WorkflowRun, run_id)
        run.status = {"proposed": "completed", "no_action": "completed",
                      "awaiting_info": "paused"}.get(final.get("outcome"), "escalated")  # fmt: skip
        run.step_count = final.get("step_count", 0)
        run.llm_calls = snapshot.get("calls", 0)
        if final.get("outcome") == "escalated":
            run.error = final.get("reason")
    return {**final, "run_id": str(run_id), "llm": snapshot}


def escalate_now(engine: Engine, state: dict, reason: str) -> None:
    """Escalate a case without running the graph (e.g. the models can't be built)."""
    _finish(Deps(engine=engine, classifier=None, resolver=None, embedder=None), state,
            "escalated", reason)  # fmt: skip
