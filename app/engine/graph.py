"""The case loop as a LangGraph graph (PROJECT.md section 8): classify -> investigate ->
policy -> resolve -> propose -> approve -> execute -> verify.

Routing: missing info or a low-confidence guess -> one templated question, then pause until
the customer replies (resume_case "info"); no policy or conflicting policies -> escalate; a
draft code rejects -> one repair attempt, then escalate; the model choosing "none" ->
escalate for a person to confirm (an LLM never closes a case on its own); more than MAX_STEPS
steps, the LLM budget, or any error -> escalate.

Interrupt/resume: the graph is compiled with a Postgres checkpointer (schema lg, see
app/engine/checkpoint.py) on thread "<tenant_id>:<case_id>". A proposal with no auto-approval
pauses at `approve` (interrupt) and resumes on the same thread when the decision is recorded,
even in another process. Nodes that pause (approve, wait_info) have no side effects, since
LangGraph re-runs a resumed node from its start; side effects live in the nodes before them.
The decision itself is read from the database (bound to the payload hash), never taken from
the resume value.

Every node opens its own short tenant transaction; no transaction is open during an LLM,
embedding or provider call (hard rule 5). Agents only read: the proposal is created by code
(create_proposal), after strict param validation, case binding, eligibility and citation
checks; execution and verification are code (executor, verifier). Text shown to the customer
is templated by code, never written by a model (rule 7).
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import Engine, func, select, update

from app.actions.base import Facts, enabled_actions, get_action
from app.agents import tools
from app.agents.prompts import classifier_messages, resolution_messages
from app.agents.schemas import Classification, ResolutionDraft
from app.core import audit, events
from app.core.business_time import business_date
from app.core.db import tenant_session
from app.core.i18n import case_language
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Execution,
    Ticket,
    TicketMessage,
    WorkflowRun,
)
from app.core.settings_resolver import tenant_pack
from app.engine import lifecycle
from app.engine.checkpoint import open_checkpointer, thread_config, thread_id
from app.engine.dispatch import run_approved
from app.engine.eligibility import order_facts
from app.engine.needs import NEED_DETAILS, NEED_ORDER, question_for
from app.engine.privacy import ESCALATION_REASON, PRIVACY_CATEGORY
from app.engine.proposals import ProposalError, create_proposal
from app.engine.resolver import Remedy, decide_remedy
from app.llm.providers import LLMError
from app.rag.retrieve import search_policies

log = logging.getLogger(__name__)

MAX_STEPS = 12
# A 'running' run older than this died with its process (restart, OOM); it is taken over.
RUN_TTL = timedelta(minutes=10)
POLICY_K = 6
# The conversation the classifier sees after replies (oldest text dropped first).
MAX_MESSAGE = 4000
# Graph supersteps per invoke: the step budget plus code-only nodes and approve re-checks.
RECURSION_LIMIT = MAX_STEPS + 12
NO_PAUSED_WORKFLOW = "no paused workflow"
# A failure before the claim (e.g. the database blipped): nothing changed, try again later.
RESUME_ERROR = "resume failed before the claim"


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
    # Working data of the run in this process (message, evidence, citations, draft, reason).
    # Deliberately NOT graph state: checkpoints hold ids and codes only (DECISIONS.md, E4.1).
    scratch: dict = field(default_factory=dict)


class CaseState(TypedDict, total=False):
    tenant_id: str
    case_id: str
    run_id: str
    category: str | None  # a code from the tenant's own category list
    need: str | None  # NEED_ORDER | NEED_DETAILS
    proposal_id: str | None
    approval_status: str | None  # pending | approved | rejected
    execution_status: str | None  # executed | declined | escalated | approved (no executor)
    # proposed | awaiting_info | approved | declined | processing | resolved | escalated | skipped
    outcome: str
    step_count: int


class _QueryVector:
    """An embedder stand-in holding a vector computed before the DB session opened."""

    def __init__(self, vector: list[float]):
        self.vector = vector

    def embed_query(self, _query: str) -> list[float]:
        return self.vector


def _work(deps: Deps, state: CaseState) -> dict:
    """This run's working data, kept out of the checkpoint (it holds customer text, order data,
    policy text and model output). A node that needs data a dead process took with it fails
    and the run escalates; the message is re-read from the database."""
    return deps.scratch.setdefault(state.get("run_id", ""), {})


def _message(deps: Deps, state: CaseState) -> str:
    w = _work(deps, state)
    if "message" not in w:  # a resumed run: the customer's words are in the ticket
        with tenant_session(uuid.UUID(state["tenant_id"]), deps.engine) as s:
            bodies = s.scalars(
                select(TicketMessage.body)
                .join(Ticket, Ticket.id == TicketMessage.ticket_id)
                .where(Ticket.case_id == uuid.UUID(state["case_id"]),
                       TicketMessage.author == "customer")
                .order_by(TicketMessage.sent_at, TicketMessage.id)
            ).all()  # fmt: skip
        w["message"] = "\n".join(bodies)[-MAX_MESSAGE:]
    return w["message"]


def _step(state: CaseState) -> int:
    return state.get("step_count", 0) + 1


def _privacy_guard(w: dict, out: CaseState) -> CaseState:
    """A privacy/grievance request never reaches the model that drafts remedies (S5.5)."""
    if out["category"] == PRIVACY_CATEGORY:
        w["reason"] = ESCALATION_REASON
        return {**out, "outcome": "escalated"}
    return out


def build_graph(deps: Deps, checkpointer=None):
    def classify(state: CaseState) -> CaseState:
        step = _step(state)
        w = _work(deps, state)
        message = _message(deps, state)
        with tenant_session(uuid.UUID(state["tenant_id"]), deps.engine) as s:
            case = s.get(Case, uuid.UUID(state["case_id"]))
            pack = tenant_pack(s)
            categories, vocabulary = list(pack.issue_categories), dict(pack.vocabulary)
            known = case.category
        if known:  # the customer already chose a category (form): no LLM call needed
            return _privacy_guard(w, {"category": known, "need": None, "step_count": step})
        result: Classification = deps.classifier.invoke_structured(
            classifier_messages(message, categories, vocabulary), Classification
        )
        unsure = (
            result.category not in categories
            or result.confidence < deps.min_confidence
            or bool(result.needs_info)
        )
        if unsure:  # the classifier's own wording stays internal (audit), never shown
            w["reason"] = f"classifier unsure: {result.model_dump_json()[:300]}"
            return {"category": None, "need": NEED_DETAILS, "step_count": step}
        with tenant_session(uuid.UUID(state["tenant_id"]), deps.engine) as s:
            case_id = uuid.UUID(state["case_id"])
            s.get(Case, case_id).category = result.category  # validated above
            s.execute(
                update(Ticket).where(Ticket.case_id == case_id).values(category=result.category)
            )
        return _privacy_guard(w, {"category": result.category, "need": None, "step_count": step})

    def investigate(state: CaseState) -> CaseState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        with tenant_session(tid, deps.engine) as s:
            evidence = gather_evidence(s, tid, s.get(Case, uuid.UUID(state["case_id"])))
        if evidence is None:
            return {"need": NEED_ORDER, "step_count": step}
        _work(deps, state)["evidence"] = evidence
        return {"step_count": step}

    def policy(state: CaseState) -> CaseState:
        query = f"{state['category'].replace('_', ' ')}: {_message(deps, state)}"
        update = retrieve_policies(deps, state, query)
        return {**update, "step_count": _step(state)}

    def resolve(state: CaseState) -> CaseState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        w = _work(deps, state)
        order_id = w["evidence"]["order"]["transaction_id"]
        with tenant_session(tid, deps.engine) as s:
            actions = enabled_actions(tenant_pack(s).actions)
            _, facts = order_facts(s, uuid.UUID(order_id))
            ceiling = decide_remedy(s, s.get(Case, uuid.UUID(state["case_id"])))
        if ceiling.action is None:  # business rules allow nothing automatic: a person decides
            w["reason"] = f"business rules: {ceiling.reason}"
            return {"outcome": "escalated", "step_count": step}
        # The model may only propose this action, at or below this amount (the tenant's
        # configured rule); it can still choose less, or escalate.
        actions = {ceiling.action: actions[ceiling.action]}
        rule = {"action": ceiling.action, "params": ceiling.params, "reason": ceiling.reason}
        evidence = {**w["evidence"], "business_rule_ceiling": rule}
        schemas = {name: cls.Input.model_json_schema() for name, cls in actions.items()}
        allowed_refs = {c["section_ref"] for c in w["citations"]}
        errors: list[str] = []
        for _attempt in range(2):  # the draft, plus one repair if code rejects it
            draft: ResolutionDraft = deps.resolver.invoke_structured(
                resolution_messages(_message(deps, state), state["category"], evidence,
                                    w["citations"], schemas, errors or None),
                ResolutionDraft,
            )  # fmt: skip
            if draft.action == "escalate":
                w["reason"] = draft.reason
                return {"outcome": "escalated", "step_count": step}
            if draft.action == "none":  # a person confirms "no compensation", not the model
                w["reason"] = f"agent suggests no compensation: {draft.reason}"
                return {"outcome": "escalated", "step_count": step}
            errors = _check_draft(draft, actions, facts, allowed_refs, order_id, ceiling)
            if not errors:
                w["reason"], w["draft"] = draft.reason, draft.model_dump()
                return {"step_count": step}
        w["reason"] = "proposal rejected by code: " + "; ".join(errors)
        return {"outcome": "escalated", "step_count": step}

    def propose(state: CaseState) -> CaseState:
        return store_proposal(deps, state)

    def approve(state: CaseState) -> CaseState:
        """Pause for a human unless an approval exists. No side effects (re-run on resume)."""
        decision = _decision(deps, state)
        if decision is None:
            interrupt({"kind": "approval", "proposal_id": state["proposal_id"]})
            decision = _decision(deps, state)  # the database is the truth, not the resume value
        if decision is None:  # woken without a decision: pause again
            return {"approval_status": "pending"}
        outcome = "declined" if decision == "rejected" else "approved"
        return {"approval_status": decision, "outcome": outcome}

    def execute(state: CaseState) -> CaseState:
        result = lifecycle.execute_approved(
            deps.engine, uuid.UUID(state["tenant_id"]), uuid.UUID(state["proposal_id"]), deps.now
        )
        outcome = {"executed": "processing"}.get(result, result)
        return {"execution_status": result, "outcome": outcome}

    def verify(state: CaseState) -> CaseState:
        result = lifecycle.verify_executed(
            deps.engine, uuid.UUID(state["tenant_id"]), uuid.UUID(state["proposal_id"])
        )
        return {"outcome": result}

    def ask(state: CaseState) -> CaseState:
        return ask_customer(deps, state)

    def wait_info(state: CaseState) -> CaseState:
        """Pause until the customer replies. No side effects (re-run on resume)."""
        interrupt({"kind": "info"})  # the reply is in the ticket (read from the DB), not here
        w = _work(deps, state)
        w.pop("message", None)  # re-read the whole conversation
        w.pop("reason", None)
        return {"need": None, "outcome": "resumed"}

    def escalate(state: CaseState) -> CaseState:
        return escalate_case(deps, state)

    def route_after(node: str):
        def route(state: CaseState) -> str:
            if state.get("step_count", 0) >= MAX_STEPS or state.get("outcome") == "escalated":
                return "escalate"
            if node in ("classify", "investigate") and state.get("need"):
                return "ask"
            return {"classify": "investigate", "investigate": "policy", "policy": "resolve",
                    "resolve": "propose"}[node]  # fmt: skip

        return route

    def after_propose(state: CaseState) -> str:
        # skipped: a person took the case over while this run worked (nothing was stored)
        return (
            "escalate"
            if state.get("outcome") == "escalated"
            else (END if state.get("outcome") == "skipped" else "approve")
        )

    def after_approve(state: CaseState) -> str:
        status = state.get("approval_status")
        if status == "pending":
            return "approve"
        return "execute" if status == "approved" else END

    def after_execute(state: CaseState) -> str:
        return "verify" if state.get("execution_status") == "executed" else END

    g = StateGraph(CaseState)
    for name, fn in [("classify", classify), ("investigate", investigate), ("policy", policy),
                     ("resolve", resolve), ("propose", propose), ("approve", approve),
                     ("execute", execute), ("verify", verify), ("ask", ask),
                     ("wait_info", wait_info), ("escalate", escalate)]:  # fmt: skip
        g.add_node(name, fn)
    g.set_entry_point("classify")
    for node in ("classify", "investigate", "policy", "resolve"):
        g.add_conditional_edges(node, route_after(node))
    g.add_conditional_edges("propose", after_propose)
    g.add_conditional_edges("approve", after_approve)
    g.add_conditional_edges("execute", after_execute)
    g.add_edge("ask", "wait_info")
    g.add_edge("wait_info", "classify")
    for terminal in ("verify", "escalate"):
        g.add_edge(terminal, END)
    return g.compile(checkpointer=checkpointer)


def _decision(deps: Deps, state: CaseState) -> str | None:
    """approved | rejected | None (no decision yet), for this state's proposal."""
    tid = uuid.UUID(state["tenant_id"])
    with tenant_session(tid, deps.engine) as s:
        proposal = s.get(ActionProposal, uuid.UUID(state["proposal_id"]))
        if proposal is None or str(proposal.case_id) != state["case_id"]:
            return "rejected"  # never act on a proposal that is not this case's
        return s.scalar(select(Approval.decision).where(Approval.proposal_id == proposal.id))


def gather_evidence(s, tid: uuid.UUID, case: Case) -> dict | None:
    """What the read tools return for the case's own order, or None if the case has no order
    the customer owns (then the customer is asked which order)."""
    if case.transaction_id is None:
        return None
    scope = tools.Scope(tid, case.id, case.customer_id)
    order_ref = str(case.transaction_id)
    order = tools.get_transaction(s, scope, order_ref)
    if not order["ok"]:
        return None
    order_row, facts = order_facts(s, case.transaction_id)
    return {
        "order": order["data"],
        "fulfilment": tools.get_fulfilment(s, scope, order_ref),
        "payments": tools.get_payment(s, scope, order_ref),
        "customer": tools.get_customer(s, scope),
        "previous_cases": tools.get_case_history(s, scope),
        "refundable_paise": facts.refundable_paise,
        # Dated policies are judged on the tenant's calendar date of the order.
        "order_business_date": business_date(order_row.placed_at, facts.settings).isoformat(),
        "missing_items_value_paise": sum(
            i["unit_price_paise"] * (i["quantity"] - i["quantity_fulfilled"])
            for i in order["data"]["items"]
        ),
    }


def retrieve_policies(deps: Deps, state: CaseState, query: str) -> CaseState:
    """Policies in force for the order (its date, brand, location), as citations in the run's
    scratch (policy text is never checkpointed); escalates when none apply or they conflict.
    The query is embedded before the transaction opens."""
    w = _work(deps, state)
    evidence = w["evidence"]
    order = evidence["order"]
    vector = _QueryVector(deps.embedder.embed_query(query))
    with tenant_session(uuid.UUID(state["tenant_id"]), deps.engine) as s:
        findings = search_policies(
            s,
            vector,
            query,
            as_of=date.fromisoformat(evidence["order_business_date"]),  # order date
            brand_id=uuid.UUID(order["brand_id"]),
            location_id=uuid.UUID(order["location_id"]),
            k=POLICY_K,
        )
    w["citations"] = [
        {"section_ref": c.section_ref, "version": c.version, "scope": c.scope,
         "heading": c.heading, "text": c.text, "doc_key": c.doc_key, "topic": c.topic}
        for c in findings.citations
    ]  # fmt: skip
    if findings.missing:
        w["reason"] = "no policy in effect covers this case"
        return {"outcome": "escalated"}
    if findings.conflicts:
        w["reason"] = "conflicting policies: " + "; ".join(findings.conflicts)
        return {"outcome": "escalated"}
    return {}


def store_proposal(deps: Deps, state: CaseState) -> CaseState:
    """Code creates the proposal from a checked draft (in the run's scratch), with the
    citations the draft relied on, and applies the tenant's auto-approval rules."""
    step = _step(state)
    w = _work(deps, state)
    draft = ResolutionDraft.model_validate(w["draft"])
    tid = uuid.UUID(state["tenant_id"])
    now = deps.now or datetime.now(UTC)
    cited = set(draft.citations)
    citations = [
        {"section_ref": c["section_ref"], "doc_key": c["doc_key"], "version": c["version"]}
        for c in w["citations"]
        if c["section_ref"] in cited
    ]
    try:
        with tenant_session(tid, deps.engine) as s:
            # The sweeper may have escalated a run that outlived its TTL: then a person
            # owns the case and this (late) run must not add a proposal to it.
            case = s.scalar(
                select(Case).where(Case.id == uuid.UUID(state["case_id"])).with_for_update()
            )
            if case.status != "investigating":
                w["reason"] = f"case is {case.status}"
                return {"outcome": "skipped", "step_count": step}
            proposal = create_proposal(
                s, tid, case_id=uuid.UUID(state["case_id"]), action=draft.action,
                params=draft.params, reason=draft.reason, citations=citations,
                run_id=uuid.UUID(state["run_id"]),
            )  # fmt: skip
            # Same as the deterministic path: auto-approval only where settings allow.
            lifecycle.proposal_made(s, tid, case, proposal.id, now)
            proposal_id = str(proposal.id)
    except ProposalError as exc:
        w["reason"] = f"proposal refused: {exc}"
        return {"outcome": "escalated", "step_count": step}
    return {"outcome": "proposed", "proposal_id": proposal_id, "step_count": step}


def ask_customer(deps: Deps, state: CaseState) -> CaseState:
    need = state.get("need") or NEED_DETAILS
    question = question_for(need)
    reason = _work(deps, state).get("reason") or question
    _finish(deps, state, "awaiting_info", reason, ticket=question, need=need)
    return {"outcome": "awaiting_info", "step_count": _step(state)}


def escalate_case(deps: Deps, state: CaseState) -> CaseState:
    w = _work(deps, state)
    reason = w.get("reason") or (
        "step limit reached" if state.get("step_count", 0) >= MAX_STEPS else "needs a person"
    )
    _finish(deps, state, "escalated", reason)
    w["reason"] = reason
    return {"outcome": "escalated", "step_count": _step(state)}


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


FINISHABLE_FROM = {
    "awaiting_info": ("investigating",),
    "escalated": lifecycle.ESCALATABLE,
}


def _finish(
    deps: Deps, state: CaseState, status: str, reason: str, ticket: str = "", need: str = ""
) -> None:
    """Set the case status, audit why, emit case.<status>; `ticket` is code-written text for
    the customer. The event payload carries no reason text (it may quote the model)."""
    tid = uuid.UUID(state["tenant_id"])
    now = deps.now or datetime.now(UTC)
    with tenant_session(tid, deps.engine) as s:
        case = s.scalar(
            select(Case).where(Case.id == uuid.UUID(state["case_id"])).with_for_update()
        )
        # Only from a status this transition may leave: a case a person closed, or that is
        # resolved or already escalated, is never moved (no status, audit, event or message).
        if case is None or case.status not in FINISHABLE_FROM[status]:
            return
        case.status = status
        if ticket:
            if need:  # the question in the customer's own language (code-owned template)
                ticket = question_for(need, case_language(s, case))
            ticket_id = s.scalar(select(Ticket.id).where(Ticket.case_id == case.id))
            if ticket_id is not None:
                s.add(TicketMessage(tenant_id=tid, ticket_id=ticket_id, author="system",
                                    body=ticket, sent_at=now))  # fmt: skip
        payload = {"reason": reason[:500]}
        if need:  # a code, not text: the customer-facing question is looked up from it
            payload["need"] = need
        audit.record(s, tid, actor_type="agent", actor_id=None, event=f"case.{status}",
                     entity_type="case", entity_id=case.id, payload=payload)  # fmt: skip
        events.emit(s, tid, f"case.{status}", case.id, {"run_id": state.get("run_id")})


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


def _claim_resume(
    engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, run_id: uuid.UUID, kind: str
) -> bool:
    """Take the paused run back (paused -> running) under the case row lock, so two resumes
    (a double-clicked reply, two workers) can't both continue the thread. A run left
    'running' past RUN_TTL died with its process and is taken over."""
    with tenant_session(tenant_id, engine) as s:
        case = s.scalar(select(Case).where(Case.id == case_id).with_for_update())
        if case is None or (kind == "info" and case.status != "awaiting_info"):
            return False
        stale = WorkflowRun.updated_at < func.now() - RUN_TTL
        taken = s.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == run_id,
                WorkflowRun.case_id == case_id,
                (WorkflowRun.status == "paused") | ((WorkflowRun.status == "running") & stale),
            )
            .values(status="running", error=None)
        ).rowcount
        if not taken:
            return False
        if kind == "info":
            case.status = "investigating"
        return True


def _pending(snapshot, kind: str | None = None) -> dict | None:
    """The interrupt the thread is paused at (optionally of one kind), else None."""
    for task in snapshot.tasks:
        for pending in task.interrupts:
            value = pending.value
            if isinstance(value, dict) and (kind is None or value.get("kind") == kind):
                return value
    return None


def _invoke(deps: Deps, saver, tenant_id, case_id, payload, build) -> tuple[dict, bool]:
    app = build(deps, saver)
    config = {**thread_config(tenant_id, case_id), "recursion_limit": RECURSION_LIMIT}
    app.invoke(payload, config)
    snapshot = app.get_state(config)
    return dict(snapshot.values), _pending(snapshot) is not None


def _guarded(deps: Deps, base: CaseState, work) -> tuple[dict, bool]:
    """Run the graph; any failure - LLM (budget, rate limits, invalid output after repair) or
    not - escalates the case to a person, so a case is never left in 'investigating'."""
    try:
        return work()
    except Exception as exc:
        kind = "LLM" if isinstance(exc, LLMError) else "internal error"
        if not isinstance(exc, LLMError):
            log.exception("agent run %s failed", base.get("run_id"))
        else:  # provider names and error classes only, never customer text
            log.warning(
                "agent run %s: %s: %s", base.get("run_id"), type(exc).__name__, str(exc)[:200]
            )
        if _has_execution(deps, base):
            # Money may be in flight: reconcile/verify own the case from here (it stays
            # 'executing'); escalating would hide a refund that may still land.
            return {**base, "outcome": "processing", "keep_checkpoint": True,
                    "reason": f"{kind} after execution: {type(exc).__name__}"}, False  # fmt: skip
        final = {**base, "outcome": "escalated", "reason": f"{kind}: {type(exc).__name__}"}
        try:
            _finish(deps, final, "escalated", final["reason"])
        except Exception:
            log.exception("could not escalate case %s", base.get("case_id"))
        return final, False


def _has_execution(deps: Deps, state: dict) -> bool:
    """Did an execution row already exist for one of this case's proposals?"""
    try:
        with tenant_session(uuid.UUID(state["tenant_id"]), deps.engine) as s:
            return s.scalar(
                select(Execution.id)
                .join(ActionProposal, ActionProposal.id == Execution.proposal_id)
                .where(ActionProposal.case_id == uuid.UUID(state["case_id"]))
                .limit(1)
            ) is not None  # fmt: skip
    except Exception:
        log.exception("could not look for executions of case %s", state.get("case_id"))
        return False


def _still_paused(deps: Deps, tenant_id, final: dict, paused: bool) -> bool:
    """A graph paused at approve whose proposal already has a decision (it landed while the
    first pass was still running) must not stay 'paused' forever: nobody would resume it, and
    the decision task's code path already ran or will run (execute is idempotent)."""
    proposal_id = final.get("proposal_id")
    if not paused or not proposal_id:
        return paused
    with tenant_session(tenant_id, deps.engine) as s:
        decided = s.scalar(
            select(Approval.id).where(Approval.proposal_id == uuid.UUID(proposal_id))
        )
    return decided is None


def _record(deps: Deps, tenant_id, run_id: uuid.UUID, final: dict, paused: bool, budget) -> dict:
    """Write the run's status and counters. The case is already where it should be; a
    failure here only leaves the run row stale (taken over after RUN_TTL)."""
    snapshot = budget.snapshot() if budget is not None else {}
    try:
        with tenant_session(tenant_id, deps.engine) as s:
            run = s.get(WorkflowRun, run_id)
            if paused:
                run.status = "paused"
            elif final.get("outcome") == "skipped":  # the sweeper already failed this run
                run.status = "failed"
            else:
                run.status = "escalated" if final.get("outcome") == "escalated" else "completed"
            run.step_count = final.get("step_count", 0)
            run.llm_calls = (run.llm_calls or 0) + snapshot.get("calls", 0)
            if final.get("outcome") == "escalated":
                run.error = (final.get("reason") or "")[:500]
    except Exception:
        log.exception("could not record the result of run %s", run_id)
    return snapshot


def _prune(deps: Deps, tenant_id: uuid.UUID, case_id: uuid.UUID) -> None:
    """A finished run's checkpoints are deleted: nothing resumes them, and the database holds
    the facts. Best effort (prune_finished sweeps what this misses)."""
    try:
        with open_checkpointer(deps.engine) as saver:
            saver.delete_thread(thread_id(tenant_id, case_id))
    except Exception:
        log.exception("could not prune the checkpoints of case %s", case_id)


def prune_finished(engine: Engine, tenant_id: uuid.UUID) -> int:
    """Sweeper entry point: delete checkpoint threads of this tenant's cases whose runs have
    all finished (completed, escalated, failed) and none is paused or running. Returns the
    number of threads deleted."""
    with tenant_session(tenant_id, engine) as s:
        live = select(WorkflowRun.case_id).where(WorkflowRun.status.in_(("paused", "running")))
        case_ids = list(s.scalars(
            select(WorkflowRun.case_id).where(WorkflowRun.case_id.not_in(live)).distinct()
        ))  # fmt: skip
    if not case_ids:
        return 0
    with open_checkpointer(engine) as saver:
        for case_id in case_ids:
            saver.delete_thread(thread_id(tenant_id, case_id))
    return len(case_ids)


def _returned(deps: Deps, run_id: str) -> dict:
    """What callers (tests, logs) see beyond the checkpointed codes; popped, never stored."""
    w = deps.scratch.pop(run_id, {})
    return {k: w[k] for k in ("reason", "evidence", "citations", "draft") if k in w}


def run_case(
    deps: Deps,
    tenant_id: uuid.UUID,
    case_id: uuid.UUID,
    message: str,
    budget,
    build=build_graph,
) -> dict:
    """Start the graph for a new case on its thread; record a workflow_runs row. The run
    ends 'paused' when the graph waits for an approval or the customer's reply. `build`
    makes the graph: the specialist pipeline, or the single-call baseline (evals); both keep
    text out of the checkpoint (it lives in `deps.scratch`)."""
    run_id = _claim(deps.engine, tenant_id, case_id)
    if run_id is None:
        return {"outcome": "skipped", "reason": "case is not waiting for a run"}
    state: CaseState = {"tenant_id": str(tenant_id), "case_id": str(case_id),
                        "run_id": str(run_id), "step_count": 0}  # fmt: skip
    deps.scratch[str(run_id)] = {"message": message}

    def work():
        with open_checkpointer(deps.engine) as saver:
            return _invoke(deps, saver, tenant_id, case_id, state, build)

    final, paused = _guarded(deps, state, work)
    paused = _still_paused(deps, tenant_id, final, paused)
    snapshot = _record(deps, tenant_id, run_id, final, paused, budget)
    _execute_if_graph_stopped_early(deps, tenant_id, case_id, final)
    if not paused and not final.get("keep_checkpoint"):
        _prune(deps, tenant_id, case_id)
    return {
        **_returned(deps, str(run_id)),
        **final,
        "run_id": str(run_id),
        "llm": snapshot,
        "paused": paused,
    }


def _execute_if_graph_stopped_early(
    deps: Deps, tenant_id: uuid.UUID, case_id: uuid.UUID, final: dict
) -> None:
    """The single-call baseline graph ends at `propose` (it has no approve/execute nodes). If
    the tenant's rule auto-approved its proposal, run it through the same single execution
    path the agent graph's execute node uses, now that the propose step has committed (rule
    5). A crash here is picked up by the sweeper (same stable key)."""
    proposal_id = final.get("proposal_id")
    if final.get("outcome") != "proposed" or not proposal_id:
        return
    try:
        ids = {"tenant_id": str(tenant_id), "case_id": str(case_id), "proposal_id": proposal_id}
        if _decision(deps, ids) == "approved":
            run_approved(deps.engine, tenant_id, uuid.UUID(proposal_id))
    except Exception:
        log.exception("could not execute proposal %s", proposal_id)


RESUME_KINDS = ("approval", "info")


def resume_case(
    deps: Deps, tenant_id: uuid.UUID, case_id: uuid.UUID, kind: str, value: dict, budget=None
) -> dict:
    """Continue the case's paused thread with `value` (e.g. the customer's reply). Works in
    any process: the state comes from the Postgres checkpoint. `tenant_id` comes from the
    auth/system context and `case_id` from a record loaded under it, never from input.

    Returns outcome "skipped" with reason NO_PAUSED_WORKFLOW when the thread isn't paused
    at a `kind` interrupt (callers may then fall back to the code path)."""
    if kind not in RESUME_KINDS:
        raise ValueError(f"unknown resume kind {kind!r}")
    run_id = None
    try:
        # The case is loaded under the tenant's own RLS session first: an id that is not
        # this tenant's case stops here, before any checkpoint is read.
        with tenant_session(tenant_id, deps.engine) as s:
            if s.get(Case, case_id) is None:
                return {"outcome": "skipped", "reason": NO_PAUSED_WORKFLOW}
        with open_checkpointer(deps.engine) as saver:
            snapshot = build_graph(deps, saver).get_state(thread_config(tenant_id, case_id))
            values = dict(snapshot.values or {})
            if (  # the stored thread must belong to this very tenant and case
                _pending(snapshot, kind) is None
                or values.get("tenant_id") != str(tenant_id)
                or values.get("case_id") != str(case_id)
            ):
                return {"outcome": "skipped", "reason": NO_PAUSED_WORKFLOW}
            claimed = uuid.UUID(values["run_id"])
            if not _claim_resume(deps.engine, tenant_id, case_id, claimed, kind):
                return {"outcome": "skipped", "reason": "workflow is busy or not waiting"}
            run_id = claimed
            final, paused = _guarded(
                deps,
                values,
                lambda: _invoke(
                    deps, saver, tenant_id, case_id, Command(resume=value), build_graph
                ),
            )
    except Exception as exc:
        log.exception("could not resume case %s", case_id)
        if run_id is None:  # nothing was claimed or resumed: the thread may well be fine
            return {"outcome": "skipped", "reason": RESUME_ERROR}
        # Claimed, then failed (e.g. the connection dropped): a person takes over, so the
        # case is never left in 'investigating' with the reply unread.
        final, paused = {"outcome": "escalated", "reason": f"internal error: {type(exc).__name__}",
                         "step_count": 0}, False  # fmt: skip
        try:
            escalate_now(deps.engine, tenant_id, case_id, final["reason"])
        except Exception:
            log.exception("could not escalate case %s", case_id)
    paused = _still_paused(deps, tenant_id, final, paused)
    snapshot_llm = _record(deps, tenant_id, run_id, final, paused, budget)
    if not paused and not final.get("keep_checkpoint"):
        _prune(deps, tenant_id, case_id)
    return {
        **_returned(deps, str(run_id)),
        **final,
        "run_id": str(run_id),
        "llm": snapshot_llm,
        "paused": paused,
    }


def escalate_now(engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, reason: str) -> None:
    """Escalate a case without running the graph (e.g. the models can't be built)."""
    deps = Deps(engine=engine, classifier=None, resolver=None, embedder=None)
    _finish(deps, {"tenant_id": str(tenant_id), "case_id": str(case_id)}, "escalated", reason)
