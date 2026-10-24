"""The case loop as a LangGraph graph (PROJECT.md section 8): classify -> investigate ->
policy -> resolve -> propose, stopping before approval (approval pause/resume is E4.1).

Routing: missing info or a low-confidence guess -> one templated question, pause; no policy
or conflicting policies -> escalate; a draft code rejects -> one repair attempt, then
escalate; the model choosing "none" -> escalate for a person to confirm (an LLM never closes a
case on its own); more than MAX_STEPS steps, the LLM budget, or any error -> escalate.

Every node opens its own short tenant transaction; no transaction is open during an LLM or
embedding call (hard rule 5). Agents only read: the proposal is created by code
(create_proposal), after strict param validation, case binding, eligibility and citation
checks. Text shown to the customer is templated by code, never written by a model (rule 7).
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import Engine, func, select, update

from app.actions.base import Facts, enabled_actions, get_action
from app.agents import tools
from app.agents.prompts import classifier_messages, resolution_messages
from app.agents.schemas import Classification, ResolutionDraft
from app.core import audit
from app.core.db import tenant_session
from app.core.models import Case, Ticket, TicketMessage, WorkflowRun
from app.core.settings_resolver import tenant_pack
from app.engine.approvals import auto_decide
from app.engine.eligibility import order_facts
from app.engine.proposals import ProposalError, create_proposal
from app.engine.resolver import Remedy, decide_remedy
from app.llm.providers import LLMError
from app.rag.retrieve import search_policies

log = logging.getLogger(__name__)

MAX_STEPS = 12
# A 'running' run older than this died with its process (restart, OOM); it is taken over.
RUN_TTL = timedelta(minutes=10)
POLICY_K = 6

# What we may need from the customer -> the question code sends (no model-written text).
NEED_ORDER = "order"
NEED_DETAILS = "details"
QUESTIONS = {
    NEED_ORDER: "Which order is this about? Please pick it from your order list.",
    NEED_DETAILS: "Thanks for telling us. So we can look into it, could you tell us a bit more"
    " about what went wrong with your order (for example, which item was affected)?",
}


class StructuredLLM(Protocol):
    def invoke_structured(self, messages, schema): ...


@dataclass
class Deps:
    engine: Engine
    classifier: StructuredLLM
    resolver: StructuredLLM
    embedder: Any  # app.rag.embeddings.Embedder
    now: datetime | None = None
    min_confidence: float = 0.6


class CaseState(TypedDict, total=False):
    tenant_id: str
    case_id: str
    run_id: str
    message: str
    category: str | None
    need: str | None  # NEED_ORDER | NEED_DETAILS
    evidence: dict | None
    citations: list[dict]
    draft: dict
    proposal_id: str | None
    outcome: str  # proposed | awaiting_info | escalated | skipped
    reason: str
    step_count: int


class _QueryVector:
    """An embedder stand-in holding a vector computed before the DB session opened."""

    def __init__(self, vector: list[float]):
        self.vector = vector

    def embed_query(self, _query: str) -> list[float]:
        return self.vector


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
            return {"category": known, "need": None, "step_count": step}
        result: Classification = deps.classifier.invoke_structured(
            classifier_messages(state["message"], categories, vocabulary), Classification
        )
        unsure = (
            result.category not in categories
            or result.confidence < deps.min_confidence
            or bool(result.needs_info)
        )
        if unsure:  # the classifier's own wording stays internal (audit), never shown
            return {"category": None, "need": NEED_DETAILS, "step_count": step,
                    "reason": f"classifier unsure: {result.model_dump_json()[:300]}"}  # fmt: skip
        with tenant_session(uuid.UUID(state["tenant_id"]), deps.engine) as s:
            case_id = uuid.UUID(state["case_id"])
            s.get(Case, case_id).category = result.category  # validated above
            s.execute(
                update(Ticket).where(Ticket.case_id == case_id).values(category=result.category)
            )
        return {"category": result.category, "need": None, "step_count": step}

    def investigate(state: CaseState) -> CaseState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        with tenant_session(tid, deps.engine) as s:
            case = s.get(Case, uuid.UUID(state["case_id"]))
            scope = tools.Scope(tid, case.id, case.customer_id)
            if case.transaction_id is None:
                return {"need": NEED_ORDER, "step_count": step}
            order_ref = str(case.transaction_id)
            order = tools.get_transaction(s, scope, order_ref)
            if not order["ok"]:
                return {"need": NEED_ORDER, "step_count": step}
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
        vector = _QueryVector(deps.embedder.embed_query(query))  # before the transaction
        with tenant_session(tid, deps.engine) as s:
            findings = search_policies(
                s,
                vector,
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
        order_id = state["evidence"]["order"]["transaction_id"]
        with tenant_session(tid, deps.engine) as s:
            actions = enabled_actions(tenant_pack(s).actions)
            _, facts = order_facts(s, uuid.UUID(order_id))
            ceiling = decide_remedy(s, s.get(Case, uuid.UUID(state["case_id"])))
        if ceiling.action is None:  # business rules allow nothing automatic: a person decides
            return {"outcome": "escalated", "step_count": step,
                    "reason": f"business rules: {ceiling.reason}"}  # fmt: skip
        # The model may only propose this action, at or below this amount (the tenant's
        # configured rule); it can still choose less, or escalate.
        actions = {ceiling.action: actions[ceiling.action]}
        rule = {"action": ceiling.action, "params": ceiling.params, "reason": ceiling.reason}
        evidence = {**state["evidence"], "business_rule_ceiling": rule}
        schemas = {name: cls.Input.model_json_schema() for name, cls in actions.items()}
        allowed_refs = {c["section_ref"] for c in state["citations"]}
        errors: list[str] = []
        for _attempt in range(2):  # the draft, plus one repair if code rejects it
            draft: ResolutionDraft = deps.resolver.invoke_structured(
                resolution_messages(state["message"], state["category"], evidence,
                                    state["citations"], schemas, errors or None),
                ResolutionDraft,
            )  # fmt: skip
            if draft.action == "escalate":
                return {"outcome": "escalated", "reason": draft.reason, "step_count": step}
            if draft.action == "none":  # a person confirms "no compensation", not the model
                return {"outcome": "escalated", "step_count": step,
                        "reason": f"agent suggests no compensation: {draft.reason}"}  # fmt: skip
            errors = _check_draft(draft, actions, facts, allowed_refs, order_id, ceiling)
            if not errors:
                return {"reason": draft.reason, "step_count": step, "draft": draft.model_dump()}
        return {"outcome": "escalated", "reason": "proposal rejected by code: "
                + "; ".join(errors), "step_count": step}  # fmt: skip

    def propose(state: CaseState) -> CaseState:
        step = _step(state)
        draft = ResolutionDraft.model_validate(state["draft"])
        tid = uuid.UUID(state["tenant_id"])
        now = deps.now or datetime.now(UTC)
        cited = set(draft.citations)
        citations = [
            {"section_ref": c["section_ref"], "doc_key": c["doc_key"], "version": c["version"]}
            for c in state["citations"]
            if c["section_ref"] in cited
        ]
        try:
            with tenant_session(tid, deps.engine) as s:
                proposal = create_proposal(
                    s, tid, case_id=uuid.UUID(state["case_id"]), action=draft.action,
                    params=draft.params, reason=draft.reason, citations=citations,
                    run_id=uuid.UUID(state["run_id"]),
                )  # fmt: skip
                # Same as the deterministic path: auto-approval only where settings allow.
                approval = auto_decide(s, tid, proposal.id, now)
                case = s.get(Case, uuid.UUID(state["case_id"]))
                case.status = "executing" if approval is not None else "awaiting_approval"
                proposal_id = str(proposal.id)
        except ProposalError as exc:
            return {"outcome": "escalated", "reason": f"proposal refused: {exc}",
                    "step_count": step}  # fmt: skip
        return {"outcome": "proposed", "proposal_id": proposal_id, "step_count": step}

    def ask(state: CaseState) -> CaseState:
        question = QUESTIONS[state.get("need") or NEED_DETAILS]
        _finish(deps, state, "awaiting_info", state.get("reason") or question, ticket=question)
        return {"outcome": "awaiting_info", "step_count": _step(state)}

    def escalate(state: CaseState) -> CaseState:
        reason = state.get("reason") or (
            "step limit reached" if state.get("step_count", 0) >= MAX_STEPS else "needs a person"
        )
        _finish(deps, state, "escalated", reason)
        return {"outcome": "escalated", "reason": reason, "step_count": _step(state)}

    def route_after(node: str):
        def route(state: CaseState) -> str:
            if state.get("step_count", 0) >= MAX_STEPS or state.get("outcome") == "escalated":
                return "escalate"
            if node in ("classify", "investigate") and state.get("need"):
                return "ask"
            return {"classify": "investigate", "investigate": "policy", "policy": "resolve",
                    "resolve": "propose"}[node]  # fmt: skip

        return route

    g = StateGraph(CaseState)
    for name, fn in [("classify", classify), ("investigate", investigate), ("policy", policy),
                     ("resolve", resolve), ("propose", propose), ("ask", ask),
                     ("escalate", escalate)]:  # fmt: skip
        g.add_node(name, fn)
    g.set_entry_point("classify")
    for node in ("classify", "investigate", "policy", "resolve"):
        g.add_conditional_edges(node, route_after(node))
    for terminal in ("propose", "ask", "escalate"):
        g.add_edge(terminal, END)
    return g.compile()


def _check_draft(
    draft: ResolutionDraft,
    actions: dict,
    facts: Facts,
    allowed: set[str],
    order_id: str,
    ceiling: Remedy,
) -> list[str]:
    """Code's checks on a draft before anything is stored: the action and amount the tenant's
    business rule allows (never more), strict params, the case's own order, eligibility, and
    at least one citation from what retrieval returned. Errors go back to the model once, so
    they never echo its ids. Policy text can't raise the ceiling: it is untrusted (rule 9)."""
    if draft.action not in actions:
        return [f"action {draft.action!r} is not available"]
    action = get_action(draft.action)()
    try:
        inp = action.Input.model_validate_json(json.dumps(draft.params))
    except Exception as exc:  # pydantic ValidationError or bad JSON types
        return [f"params invalid: {str(exc)[:200]}"]
    errors = []
    field = action.amount_field
    # The validated value (strict integer paise), never the raw draft param.
    if field is not None and getattr(inp, field) > ceiling.params.get(field, 0):
        errors.append(f"{field} is above what the business rules allow for this case")
    if str(draft.params.get("transaction_id", order_id)) != order_id:
        errors.append("transaction_id must be the order in the evidence")
    errors += list(action.validate(None, inp, facts).errors)
    if not draft.citations:
        errors.append("cite at least one policy section")
    elif any(ref not in allowed for ref in draft.citations):
        errors.append("cite only the section_ref values provided")
    return errors


def _finish(deps: Deps, state: CaseState, status: str, reason: str, ticket: str = "") -> None:
    """Set the case status and audit why; `ticket` is code-written text for the customer."""
    tid = uuid.UUID(state["tenant_id"])
    now = deps.now or datetime.now(UTC)
    with tenant_session(tid, deps.engine) as s:
        case = s.get(Case, uuid.UUID(state["case_id"]))
        case.status = status
        if ticket:
            ticket_id = s.scalar(select(Ticket.id).where(Ticket.case_id == case.id))
            if ticket_id is not None:
                s.add(TicketMessage(tenant_id=tid, ticket_id=ticket_id, author="system",
                                    body=ticket, sent_at=now))  # fmt: skip
        audit.record(s, tid, actor_type="agent", actor_id=None, event=f"case.{status}",
                     entity_type="case", entity_id=case.id,
                     payload={"reason": reason[:500]})  # fmt: skip


def _claim(engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID) -> uuid.UUID | None:
    """Start a run unless the case isn't waiting for one or a live run holds it. The case row
    lock makes two concurrent claims (e.g. a resubmitted report) serialize: one wins. A run
    still 'running' after RUN_TTL is marked failed, so a crash can't block the case forever."""
    with tenant_session(tenant_id, engine) as s:
        case = s.scalar(select(Case).where(Case.id == case_id).with_for_update())
        if case is None or case.status != "investigating":
            return None
        running = (WorkflowRun.case_id == case_id) & (WorkflowRun.status == "running")
        s.execute(
            update(WorkflowRun)
            .where(running, WorkflowRun.created_at < func.now() - RUN_TTL)
            .values(status="failed", error="abandoned: no result within the run TTL")
        )
        if s.scalar(select(WorkflowRun.id).where(running)) is not None:
            return None
        run_id = uuid.uuid4()
        s.add(WorkflowRun(id=run_id, tenant_id=tenant_id, case_id=case_id, status="running"))
        return run_id


def run_case(deps: Deps, tenant_id: uuid.UUID, case_id: uuid.UUID, message: str, budget) -> dict:
    """Run the graph for one case and record a workflow_runs row with step/LLM counters.
    Any failure - LLM (budget, rate limits, invalid output after repair) or not - escalates
    the case to a person; a case is never left in 'investigating'."""
    run_id = _claim(deps.engine, tenant_id, case_id)
    if run_id is None:
        return {"outcome": "skipped", "reason": "case is not waiting for a run"}
    state: CaseState = {"tenant_id": str(tenant_id), "case_id": str(case_id),
                        "run_id": str(run_id), "message": message, "step_count": 0}  # fmt: skip
    try:
        final = build_graph(deps).invoke(state, {"recursion_limit": MAX_STEPS + 4})
    except Exception as exc:
        kind = "LLM" if isinstance(exc, LLMError) else "internal error"
        if not isinstance(exc, LLMError):
            log.exception("agent run %s failed", run_id)
        final = {**state, "outcome": "escalated", "reason": f"{kind}: {type(exc).__name__}"}
        try:
            _finish(deps, final, "escalated", final["reason"])
        except Exception:
            log.exception("could not escalate case %s", case_id)
    snapshot = budget.snapshot()
    try:  # the case is already terminal here; a failure only leaves the run row stale (TTL)
        with tenant_session(tenant_id, deps.engine) as s:
            run = s.get(WorkflowRun, run_id)
            run.status = {"proposed": "completed", "awaiting_info": "paused"}.get(
                final.get("outcome"), "escalated"
            )
            run.step_count = final.get("step_count", 0)
            run.llm_calls = snapshot.get("calls", 0)
            if final.get("outcome") == "escalated":
                run.error = (final.get("reason") or "")[:500]
    except Exception:
        log.exception("could not record the result of run %s", run_id)
    return {**final, "run_id": str(run_id), "llm": snapshot}


def escalate_now(engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, reason: str) -> None:
    """Escalate a case without running the graph (e.g. the models can't be built)."""
    deps = Deps(engine=engine, classifier=None, resolver=None, embedder=None)
    _finish(deps, {"tenant_id": str(tenant_id), "case_id": str(case_id)}, "escalated", reason)
