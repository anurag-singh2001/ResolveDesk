"""Single-agent baseline (PROJECT.md section 9: "keep the baseline runnable for comparison").

One LLM call classifies and proposes. Everything else is the specialist pipeline's code: the
same read tools and retrieval (no LLM), the same business-rule ceiling, the same draft checks
(`_check_draft`), the same `store_proposal`, templated questions and escalation. The only
differences: one prompt instead of two, the ceilings for every category are computed up front
(the category isn't known before the call), and a rejected draft escalates without a repair
call. Used by evals to measure what splitting into specialists buys.
"""

import uuid
from types import SimpleNamespace

from langgraph.graph import END, StateGraph
from sqlalchemy import update

from app.actions.base import enabled_actions
from app.agents.prompts import baseline_messages
from app.agents.schemas import BaselineDecision, ResolutionDraft
from app.core.db import tenant_session
from app.core.models import Case, Ticket
from app.core.settings_resolver import tenant_pack
from app.engine.eligibility import order_facts
from app.engine.graph import (
    MAX_STEPS,
    NEED_DETAILS,
    NEED_ORDER,
    CaseState,
    Deps,
    _check_draft,
    _message,
    _step,
    _work,
    ask_customer,
    escalate_case,
    gather_evidence,
    retrieve_policies,
    store_proposal,
)
from app.engine.privacy import ESCALATION_REASON, PRIVACY_CATEGORY
from app.engine.resolver import Remedy, decide_remedy

BaselineState = CaseState  # ids and codes only; ceilings, evidence, text live in deps.scratch


def remedy_probe(case, category: str) -> SimpleNamespace:
    """Duck-typed stand-in for decide_remedy: it reads only these three attributes. The
    customer's pick (S7.9) applies to the case's own category only, never to the others."""
    return SimpleNamespace(
        category=category,
        transaction_id=case.transaction_id,
        remedy_choice=case.remedy_choice if category == case.category else None,
    )


def build_baseline_graph(deps: Deps, checkpointer=None):
    def gather(state: BaselineState) -> BaselineState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        w = _work(deps, state)
        with tenant_session(tid, deps.engine) as s:
            case = s.get(Case, uuid.UUID(state["case_id"]))
            evidence = gather_evidence(s, tid, case)
            if evidence is None:
                return {"need": NEED_ORDER, "step_count": step}
            categories = list(tenant_pack(s).issue_categories)
            ceilings = {}
            for category in categories:  # duck-typed: decide_remedy reads only these three
                probe = remedy_probe(case, category)
                r = decide_remedy(s, probe)
                ceilings[category] = {
                    "action": r.action,
                    "params": r.params,
                    "reason": r.reason,
                    "outcome": r.outcome,
                }
        w["evidence"], w["ceilings"] = evidence, ceilings
        update_ = retrieve_policies(deps, state, _message(deps, state))
        return {**update_, "step_count": step}

    def decide(state: BaselineState) -> BaselineState:
        step = _step(state)
        tid = uuid.UUID(state["tenant_id"])
        case_id = uuid.UUID(state["case_id"])
        w = _work(deps, state)
        order_id = w["evidence"]["order"]["transaction_id"]
        with tenant_session(tid, deps.engine) as s:
            pack = tenant_pack(s)
            categories, vocabulary = list(pack.issue_categories), dict(pack.vocabulary)
            actions = enabled_actions(pack.actions)
            _, facts = order_facts(s, uuid.UUID(order_id))
            filed = s.get(Case, case_id).category
        if filed == PRIVACY_CATEGORY:  # customer-filed: never reclassified, no LLM call (S5.5)
            w["reason"] = ESCALATION_REASON
            return {"category": filed, "outcome": "escalated", "step_count": step}
        ceilings = w["ceilings"]
        offered = {c["action"] for c in ceilings.values() if c["action"] in actions}
        schemas = {name: actions[name].Input.model_json_schema() for name in sorted(offered)}
        shown = {k: {"action": v["action"], "params": v["params"]} for k, v in ceilings.items()}
        reply: BaselineDecision = deps.resolver.invoke_structured(
            baseline_messages(_message(deps, state), categories, vocabulary, w["evidence"],
                              shown, w["citations"], schemas),
            BaselineDecision,
        )  # fmt: skip
        if (
            reply.category not in categories
            or reply.confidence < deps.min_confidence
            or bool(reply.needs_info)
        ):
            w["reason"] = f"baseline unsure: {reply.model_dump_json()[:300]}"
            return {"need": NEED_DETAILS, "step_count": step}
        with tenant_session(tid, deps.engine) as s:
            s.get(Case, case_id).category = reply.category  # validated above
            s.execute(update(Ticket).where(Ticket.case_id == case_id)
                      .values(category=reply.category))  # fmt: skip
        ceiling = Remedy(**ceilings[reply.category])
        out: BaselineState = {"category": reply.category, "step_count": step}
        if ceiling.action is None:
            w["reason"] = f"business rules: {ceiling.reason}"
            return {**out, "outcome": "escalated"}
        if reply.action == "escalate":
            w["reason"] = reply.reason
            return {**out, "outcome": "escalated"}
        if reply.action == "none":
            w["reason"] = f"agent suggests no compensation: {reply.reason}"
            return {**out, "outcome": "escalated"}
        draft = ResolutionDraft(action=reply.action, params=reply.params, reason=reply.reason,
                                citations=reply.citations)  # fmt: skip
        allowed_refs = {c["section_ref"] for c in w["citations"]}
        errors = _check_draft(draft, {ceiling.action: actions[ceiling.action]}, facts,
                              allowed_refs, order_id, ceiling)  # fmt: skip
        if errors:  # one call only: no repair round
            w["reason"] = "proposal rejected by code: " + "; ".join(errors)
            return {**out, "outcome": "escalated"}
        w["reason"], w["draft"] = reply.reason, draft.model_dump()
        return out

    def route_after(node: str):
        def route(state: BaselineState) -> str:
            if state.get("step_count", 0) >= MAX_STEPS or state.get("outcome") == "escalated":
                return "escalate"
            if state.get("need"):
                return "ask"
            return {"gather": "decide", "decide": "propose"}[node]

        return route

    g = StateGraph(BaselineState)
    g.add_node("gather", gather)
    g.add_node("decide", decide)
    g.add_node("propose", lambda st: store_proposal(deps, st))
    g.add_node("ask", lambda st: ask_customer(deps, st))
    g.add_node("escalate", lambda st: escalate_case(deps, st))
    g.set_entry_point("gather")
    for node in ("gather", "decide"):
        g.add_conditional_edges(node, route_after(node))
    for terminal in ("propose", "ask", "escalate"):
        g.add_edge(terminal, END)
    return g.compile(checkpointer=checkpointer)
