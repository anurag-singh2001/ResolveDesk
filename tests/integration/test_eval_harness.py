"""Every scenario of every tenant runs through the eval harness on seeded history (no LLM:
a stand-in runner), and each scenario's expectation agrees with the tenant's business rule.
"""

from datetime import date
from types import SimpleNamespace

from sqlalchemy import delete, select

from app.core.business_time import business_date
from app.core.db import tenant_session
from app.core.models import Case, Customer, Fulfilment, Ticket, Transaction
from app.core.tenancy import tenant_id_for
from app.core.verticals import load_pack
from app.engine.eligibility import order_facts
from evals.harness import (
    existing_case_orders,
    open_case,
    run_scenarios,
    select_order,
    undo_planted,
)
from evals.scenarios import OrderSelector, load_scenarios
from tests.helpers import remove_eval_cases


def _stand_in(engine, tenant_id, case_id, message, pipeline):
    return {"outcome": "escalated", "reason": "stand-in", "llm": {"calls": 0}}


def test_every_scenario_runs_and_matches_the_business_rule(
    app_engine, maint_engine, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    scenarios = load_scenarios(tenant, cfg.slug, load_pack(cfg.vertical_pack))
    planted: list = []
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


def test_placed_on_moves_an_order_to_that_business_date_and_back(
    app_engine, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    target = date(2026, 10, 27)
    planted: list = []
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        sel = OrderSelector(select="latest")
        order = select_order(s, sel, set())
        before = (order.placed_at, _minutes_late(s, order.id))
        moved = select_order(s, sel.model_copy(update={"placed_on": target}), set(), planted)
        _, facts = order_facts(s, moved.id)
        assert moved.id == order.id
        assert business_date(moved.placed_at, facts.settings) == target
        assert _minutes_late(s, moved.id) == before[1]  # lateness is unchanged
        undo_planted(s, planted)
        s.refresh(order)
        assert order.placed_at == before[0]


def _two_scenarios(tenant, cfg):
    return load_scenarios(tenant, cfg.slug, load_pack(cfg.vertical_pack))[:2]


def test_a_case_deleted_mid_run_is_one_error_not_a_crash(
    app_engine, maint_engine, seeded_history, tenant
):
    """Sprint 7 crash 1: another process reseeded the shared database during the run, the case
    vanished, and the read-back raised AttributeError and aborted every remaining scenario."""
    cfg = seeded_history[tenant.name]
    scenarios = _two_scenarios(tenant, cfg)
    tid = tenant_id_for(cfg.slug)
    calls = []

    def vanishing(engine, tenant_id, case_id, message, pipeline):
        calls.append(case_id)
        if len(calls) == 1:  # the first case is wiped under the pipeline's feet
            with tenant_session(tid, maint_engine) as s:
                s.execute(delete(Ticket).where(Ticket.case_id == case_id))
                s.execute(delete(Case).where(Case.id == case_id))
        return {"outcome": "escalated"}

    planted: list = []
    results = []
    try:
        results = run_scenarios(app_engine, cfg.slug, scenarios, "agents", vanishing,
                                existing_case_orders(app_engine, cfg.slug),
                                planted=planted)  # fmt: skip
        assert len(results) == len(scenarios)  # the run went on
        assert results[0].outcome == "error" and "disappeared" in results[0].error
        assert results[1].outcome == "escalated" and not results[1].error
    finally:
        remove_eval_cases(app_engine, maint_engine, cfg.slug, results, planted)


def test_a_setup_failure_is_one_error_not_a_crash(
    app_engine, maint_engine, seeded_history, tenant, monkeypatch
):
    """Sprint 7 crash 2: open_case raised a ForeignKeyViolation (the customer vanished between
    the query and the insert) and aborted the whole run."""
    from sqlalchemy.exc import IntegrityError

    from evals import harness

    cfg = seeded_history[tenant.name]
    scenarios = _two_scenarios(tenant, cfg)
    real = harness.open_case
    n = []

    def flaky(s, tid, order, message):
        n.append(1)
        if len(n) == 1:
            raise IntegrityError("insert", {}, Exception("cases_tenant_id_customer_id_fkey"))
        return real(s, tid, order, message)

    monkeypatch.setattr(harness, "open_case", flaky)
    planted: list = []
    results = []
    try:
        results = run_scenarios(app_engine, cfg.slug, scenarios, "agents", _stand_in,
                                existing_case_orders(app_engine, cfg.slug),
                                planted=planted)  # fmt: skip
        assert len(results) == len(scenarios)
        assert results[0].outcome == "error" and "setup failed" in results[0].error
        assert results[1].outcome == "escalated" and not results[1].error
    finally:
        remove_eval_cases(app_engine, maint_engine, cfg.slug,
                          [r for r in results if r.case_id], planted)  # fmt: skip


def test_open_case_without_an_order_uses_this_tenants_newest_customer(
    app_engine, maint_engine, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        newest = s.scalar(select(Transaction).where(Transaction.tenant_id == tid)
                          .order_by(Transaction.placed_at.desc()).limit(1))  # fmt: skip
        case_id = open_case(s, tid, None, "where is my order?")
        s.flush()
        case = s.get(Case, case_id)
        assert case.customer_id == newest.customer_id and case.tenant_id == tid
        assert s.get(Customer, case.customer_id) is not None
    remove_eval_cases(app_engine, maint_engine, cfg.slug,
                      [SimpleNamespace(case_id=str(case_id))], [])  # fmt: skip


def _minutes_late(s, order_id):
    f = s.scalar(select(Fulfilment).where(Fulfilment.transaction_id == order_id))
    return (f.completed_at - f.promised_at).total_seconds()
