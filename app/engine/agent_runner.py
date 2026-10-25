"""Run the agent graph for a case outside any request transaction (background task)."""

import logging
import uuid

from sqlalchemy import Engine

from app.config import get_settings
from app.engine import graph
from app.engine.baseline import build_baseline_graph
from app.llm.providers import LLMClient, RunBudget
from app.rag.embeddings import FastEmbedder

log = logging.getLogger(__name__)


PIPELINES = {"agents": graph.build_graph, "baseline": build_baseline_graph}


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
    s = get_settings()
    budget = RunBudget.from_settings(s)
    try:
        deps = graph.Deps(
            engine=engine,
            classifier=LLMClient.for_role("classifier", budget=budget, settings=s),
            resolver=LLMClient.for_role("main", budget=budget, settings=s),
            embedder=FastEmbedder(),
            min_confidence=s.agent_min_confidence,
        )
    except Exception as exc:
        log.warning("agents unavailable for case %s: %s", case_id, type(exc).__name__)
        try:
            graph.escalate_now(engine, tenant_id, case_id, f"AI unavailable: {type(exc).__name__}")
        except Exception:
            log.exception("could not escalate case %s", case_id)
        return {"outcome": "escalated"}
    return graph.run_case(deps, tenant_id, case_id, message, budget, PIPELINES[pipeline])
