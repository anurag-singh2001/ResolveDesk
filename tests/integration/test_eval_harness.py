"""Every scenario of every tenant runs through the eval harness on seeded history (no LLM:
a stand-in runner), and each scenario's expectation agrees with the tenant's business rule.
"""

import uuid

from app.core.verticals import load_pack
from evals.harness import existing_case_orders, run_scenarios
from evals.scenarios import load_scenarios
from tests.helpers import remove_eval_cases


def _stand_in(engine, tenant_id, case_id, message, pipeline):
    return {"outcome": "escalated", "reason": "stand-in", "llm": {"calls": 0}}


def test_every_scenario_runs_and_matches_the_business_rule(
    app_engine, maint_engine, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    scenarios = load_scenarios(tenant, cfg.slug, load_pack(cfg.vertical_pack))
    planted: list[uuid.UUID] = []
    results = []
    try:
        results = run_scenarios(app_engine, cfg.slug, scenarios, "agents", _stand_in,
                                existing_case_orders(app_engine, cfg.slug),
                                planted=planted)  # fmt: skip
        assert len(results) == len(scenarios)
        orders = [r.order_id for r in results if r.order_id]
        assert len(orders) == len(set(orders))  # one pass never reuses an order
        for r in results:
            e = r.scenario.expect
            assert r.outcome == "escalated" and r.action is None and not r.error
            if e.outcome == "proposed":  # the rule allows exactly the expected action
                assert r.ceiling.action == e.action, r.scenario.id
                assert r.ceiling.amount and r.ceiling.amount > 0, r.scenario.id
            elif e.category is not None:  # a rule-driven escalation: nothing automatic
                assert r.ceiling.action is None, r.scenario.id
            assert (r.order_id is None) == (r.scenario.order.select == "none")
    finally:
        remove_eval_cases(app_engine, maint_engine, cfg.slug, results, planted)
