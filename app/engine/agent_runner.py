"""Run or resume the agent graph for a case outside any request transaction (background
tasks: the request's transaction has committed before these start)."""

import logging
import uuid

from sqlalchemy import Engine

from app.config import get_settings
from app.engine import graph, lifecycle
from app.engine.baseline import build_baseline_graph
from app.llm.providers import LLMClient, RunBudget
from app.rag.embeddings import FastEmbedder

log = logging.getLogger(__name__)


PIPELINES = {"agents": graph.build_graph, "baseline": build_baseline_graph}


def _deps(engine: Engine, budget: RunBudget) -> graph.Deps:
    s = get_settings()
    return graph.Deps(
        engine=engine,
        classifier=LLMClient.for_role("classifier", budget=budget, settings=s),
        resolver=LLMClient.for_role("main", budget=budget, settings=s),
        embedder=FastEmbedder(),
        min_confidence=s.agent_min_confidence,
    )


def providers_ready() -> bool:
    """Can the LLM clients be built right now (keys present, providers configured)? A cheap
    local check, no network call: the sweeper uses it so a retry is not spent while the AI is
    still unavailable."""
    try:
        s = get_settings()
        budget = RunBudget.from_settings(s)
        LLMClient.for_role("classifier", budget=budget, settings=s)
        LLMClient.for_role("main", budget=budget, settings=s)
    except Exception:
        return False
    return True


def _unavailable(engine, tenant_id, case_id, exc: Exception) -> dict:
    log.warning("agents unavailable for case %s: %s", case_id, type(exc).__name__)
    try:
        graph.escalate_now(engine, tenant_id, case_id, f"AI unavailable: {type(exc).__name__}")
    except Exception:
        log.exception("could not escalate case %s", case_id)
    return {"outcome": "escalated"}


def run_agents(
    engine: Engine,
    tenant_id: uuid.UUID,
    case_id: uuid.UUID,
    message: str,
    pipeline: str = "agents",
) -> dict:
    """Builds the LLM clients (one shared budget per run) and runs the graph (`pipeline`:
    the specialist agents, or the single-call baseline evals compare it with). If anything
    fails before the graph starts (no API key, model load error), the case is escalated to a
    person, never left hanging in 'investigating'."""
    budget = RunBudget.from_settings(get_settings())
    try:
        deps = _deps(engine, budget)
    except Exception as exc:
        return _unavailable(engine, tenant_id, case_id, exc)
    return graph.run_case(deps, tenant_id, case_id, message, budget, PIPELINES[pipeline])


def resume_info(engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, message: str) -> dict:
    """The customer replied on a case waiting for information: continue its thread with the
    reply (the graph classifies again with the whole conversation)."""
    budget = RunBudget.from_settings(get_settings())
    try:
        deps = _deps(engine, budget)
    except Exception as exc:
        return _unavailable(engine, tenant_id, case_id, exc)
    return graph.resume_case(deps, tenant_id, case_id, "info", {"kind": "info"}, budget)


def resume_after_decision(
    engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, proposal_id: uuid.UUID
) -> dict:
    """A decision was recorded: resume the case's thread paused at `approve` (it reads the
    decision from the database; its execute node is the single execution path). Returns
    outcome "skipped" when there is no paused thread to resume."""
    deps = graph.Deps(engine=engine, classifier=None, resolver=None, embedder=None)
    return graph.resume_case(
        deps, tenant_id, case_id, "approval", {"proposal_id": str(proposal_id)}
    )


def after_decision(
    engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, proposal_id: uuid.UUID, approved: bool
) -> dict:
    """resume_after_decision, then (for an approval the graph did not pick up: no paused
    thread, or the first pass hasn't marked its run paused yet) the same single execution
    path the graph uses. Safe to overlap: the executor's stable key and the verifier's
    verdict make a second pass a no-op."""
    out = resume_after_decision(engine, tenant_id, case_id, proposal_id)
    if out.get("outcome") == "skipped" and approved:
        return {"outcome": lifecycle.execute_and_verify(engine, tenant_id, proposal_id)}
    return out
