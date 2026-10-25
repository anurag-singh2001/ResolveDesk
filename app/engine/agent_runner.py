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


def after_decision(
    engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, proposal_id: uuid.UUID, approved: bool
) -> dict:
    """A decision was recorded: resume the case's thread paused at `approve` (it reads the
    decision from the database). Cases with no paused thread (the deterministic path, or a
    checkpoint that can't be reached) go straight to the code path: execute, then verify.
    Both are safe to overlap: the executor's stable key and the verifier's verdict make a
    second pass a no-op."""
    deps = graph.Deps(engine=engine, classifier=None, resolver=None, embedder=None)
    out = graph.resume_case(deps, tenant_id, case_id, "approval", {"proposal_id": str(proposal_id)})
    # Any skip (no paused thread, or the first pass hasn't marked its run paused yet) must
    # not strand an approved refund: the code path is idempotent, so run it.
    if out.get("outcome") == "skipped" and approved:
        return {"outcome": lifecycle.execute_and_verify(engine, tenant_id, proposal_id)}
    return out
