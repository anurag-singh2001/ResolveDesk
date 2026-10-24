"""E3.3 live check: `pytest -m live -k proposal` runs each tenant's scenarios tagged `live`
(3 per tenant) through the real agent graph with real LLMs, on the test database.

Asserts what code guarantees and what the scenario expects: the category, the action, an
amount at or below the tenant's business rule, escalation where expected, and that a prompt
injection buys nothing. Skipped when an LLM key for the configured providers is missing.
Not part of `make test` (marker `live`): it costs real calls and needs the network.
"""

import uuid

import pytest

from app.config import get_settings
from app.core.tenant_config import tenant_dirs
from app.core.verticals import load_pack
from app.engine.agent_runner import run_agents
from app.llm.providers import LLMClient, MissingAPIKey
from app.rag.embeddings import FastEmbedder, HashEmbedder
from app.rag.ingest import ingest_policies
from evals.harness import existing_case_orders, run_scenarios
from evals.metrics import score
from evals.scenarios import load_scenarios
from tests.helpers import remove_eval_cases

pytestmark = pytest.mark.live


@pytest.fixture(scope="session")
def llm_ready():
    s = get_settings()
    try:
        for role in ("classifier", "main"):
            LLMClient.for_role(role, settings=s)
    except MissingAPIKey as exc:
        pytest.skip(f"no LLM key: {exc.env_var} is not set")


@pytest.fixture(scope="session")
def live_policies(llm_ready, app_engine, seeded_history):
    """Policies embedded with the real model (what run_agents queries with); put back to the
    hash vectors afterwards so other test modules in the same session aren't affected."""
    for folder in tenant_dirs():
        ingest_policies(app_engine, seeded_history[folder.name].slug, folder, FastEmbedder())
    yield seeded_history
    for folder in tenant_dirs():
        ingest_policies(app_engine, seeded_history[folder.name].slug, folder, HashEmbedder())


def test_live_proposal_scenarios(app_engine, maint_engine, live_policies, tenant):
    cfg = live_policies[tenant.name]
    pack = load_pack(cfg.vertical_pack)
    scenarios = [sc for sc in load_scenarios(tenant, cfg.slug, pack) if "live" in sc.tags]
    assert len(scenarios) == 3
    planted: list[uuid.UUID] = []
    results = []
    try:
        results = run_scenarios(app_engine, cfg.slug, scenarios, "agents", run_agents,
                                existing_case_orders(app_engine, cfg.slug),
                                planted=planted)  # fmt: skip
        problems = []
        for r in results:
            e, s = r.scenario.expect, score(r)
            got = f"{r.category}/{r.outcome}/{r.action}/{r.amount} ({(r.error or r.reason)[:120]})"
            if s.over_ceiling:  # code's guarantee: never beyond the business rule
                problems.append(f"{r.scenario.id}: over the business rule: {got}")
            if r.category != e.category:
                problems.append(f"{r.scenario.id}: category {e.category} expected: {got}")
            if e.outcome == "escalated" and r.outcome != "escalated":
                problems.append(f"{r.scenario.id}: escalation expected: {got}")
            if e.action is not None and not (r.action == e.action and s.amount_within):
                problems.append(f"{r.scenario.id}: {e.action} within the rule expected: {got}")
            if s.injection_held is False:
                problems.append(f"{r.scenario.id}: injection not held: {got}")
        assert not problems, "\n".join(problems)
    finally:
        remove_eval_cases(app_engine, maint_engine, cfg.slug, results, planted)
