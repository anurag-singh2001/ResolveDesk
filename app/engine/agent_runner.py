"""Run the agent graph for a case outside any request transaction (background task)."""

import logging
import uuid

from sqlalchemy import Engine

from app.engine import graph
from app.llm.providers import LLMClient, LLMError, RunBudget
from app.rag.embeddings import FastEmbedder

log = logging.getLogger(__name__)


def run_agents(engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, message: str) -> dict:
    """Builds the LLM clients (one shared budget per run) and runs the graph. If the models
    can't even be built (e.g. no API key), the case is escalated to a person, never left
    hanging in 'investigating'."""
    budget = RunBudget.from_settings()
    try:
        deps = graph.Deps(
            engine=engine,
            classifier=LLMClient.for_role("classifier", budget=budget),
            resolver=LLMClient.for_role("main", budget=budget),
            embedder=FastEmbedder(),
        )
    except LLMError as exc:
        log.warning("agents unavailable for case %s: %s", case_id, type(exc).__name__)
        state = {"tenant_id": str(tenant_id), "case_id": str(case_id)}
        graph.escalate_now(engine, state, f"AI pipeline unavailable: {type(exc).__name__}")
        return {"outcome": "escalated"}
    return graph.run_case(deps, tenant_id, case_id, message, budget)
