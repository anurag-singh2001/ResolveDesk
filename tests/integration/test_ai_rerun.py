# ruff: noqa: F811 (pytest fixtures imported from test_cases_api)
"""S7.4 / S7.7: re-run the AI on a case that escalated because the AI was unavailable, for
every tenant. The model path is faked; what is tested is the claim, scope, audit and sweeper."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.core import audit
from app.core.db import tenant_session
from app.core.models import ActionProposal, AuditEvent, Case
from app.engine import agent_runner, ai_rerun, graph
from app.engine.sweeper import sweep_tenant
from app.llm.providers import MissingAPIKey
from tests.helpers import login
from tests.integration.test_cases_api import _open, clean_mocks, flow  # noqa: F401

AI_DOWN = "AI unavailable: MissingAPIKey"


def _escalate(app_engine, f, case_id, reason):
    """Put the case where an AI failure (or another escalation) leaves it."""
    with tenant_session(f["tid"], app_engine) as s:
        s.execute(update(Case).where(Case.id == uuid.UUID(str(case_id))).values(status="escalated"))
        audit.record(s, f["tid"], actor_type="agent", actor_id=None, event="case.escalated",
                     entity_type="case", entity_id=uuid.UUID(str(case_id)),
                     payload={"reason": reason})  # fmt: skip


@pytest.fixture
def stuck(api, app_engine, flow):
    """A case escalated for a missing API key."""
    opened = _open(api, flow)
    _escalate(app_engine, flow, opened["id"], AI_DOWN)
    return {**flow, "case_id": opened["id"], "url": f"/cases/{opened['id']}/rerun-ai"}


@pytest.fixture
def fake_runs(monkeypatch):
    """Replace the agent run: record it and leave the case 'investigating' (a run in flight)."""
    runs = []

    def fake(engine, tenant_id, case_id, message, pipeline="agents"):
        runs.append((tenant_id, case_id, message))
        return {"outcome": "proposed"}

    monkeypatch.setattr(agent_runner, "run_agents", fake)
    return runs


def _events(app_engine, f, case_id, name):
    with tenant_session(f["tid"], app_engine) as s:
        rows = s.scalars(
            select(AuditEvent).where(
                AuditEvent.event == name, AuditEvent.entity_id == uuid.UUID(str(case_id))
            )
        ).all()
        return [
            SimpleNamespace(payload=r.payload, actor_type=r.actor_type, actor_id=r.actor_id)
            for r in rows
        ]


def _proposals(app_engine, f, case_id):
    with tenant_session(f["tid"], app_engine) as s:
        return len(
            s.scalars(
                select(ActionProposal.id).where(ActionProposal.case_id == uuid.UUID(str(case_id)))
            ).all()
        )


def _status(app_engine, f, case_id):
    with tenant_session(f["tid"], app_engine) as s:
        return s.scalar(select(Case.status).where(Case.id == uuid.UUID(str(case_id))))


def test_staff_see_the_button_only_for_an_ai_failure(api, app_engine, flow):
    f = flow
    opened = _open(api, f)
    _escalate(app_engine, f, opened["id"], AI_DOWN)
    detail = api.get(f"/cases/{opened['id']}", headers=f["hq"]).json()
    assert detail["can_rerun_ai"] is True
    assert api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()["can_rerun_ai"] is False
    _escalate(app_engine, f, opened["id"], "needs a person")  # a later, different escalation
    assert api.get(f"/cases/{opened['id']}", headers=f["hq"]).json()["can_rerun_ai"] is False


def test_a_provider_failure_mid_run_is_also_rerunnable(api, app_engine, flow):
    f = flow
    opened = _open(api, f)
    _escalate(app_engine, f, opened["id"], "LLM: ProviderFailed")
    assert api.get(f"/cases/{opened['id']}", headers=f["hq"]).json()["can_rerun_ai"] is True
    _escalate(app_engine, f, opened["id"], "LLM: BudgetExceeded")  # would only repeat
    assert api.get(f"/cases/{opened['id']}", headers=f["hq"]).json()["can_rerun_ai"] is False


def test_rerun_starts_one_run_and_audits_codes_only(api, app_engine, stuck, fake_runs):
    f = stuck
    resp = api.post(f["url"], headers=f["hq"])
    assert resp.status_code == 202 and resp.json() == {"status": "started"}
    assert len(fake_runs) == 1
    assert "missing from my order" in fake_runs[0][2]  # the customer's words were re-read
    assert _status(app_engine, f, f["case_id"]) == "investigating"
    requested = _events(app_engine, f, f["case_id"], "case.ai_rerun_requested")
    result = _events(app_engine, f, f["case_id"], "case.ai_rerun_result")
    assert [e.payload["trigger"] for e in requested] == ["staff"]
    assert [e.payload["outcome"] for e in result] == ["proposed"]
    assert requested[0].actor_type == "user" and requested[0].actor_id is not None
    assert "missing" not in str([e.payload for e in requested + result])


def test_a_double_click_is_one_run(api, app_engine, stuck, fake_runs):
    f = stuck
    assert api.post(f["url"], headers=f["hq"]).json() == {"status": "started"}
    again = api.post(f["url"], headers=f["hq"])
    assert again.status_code == 202 and again.json() == {"status": "already_running"}
    assert len(fake_runs) == 1
    assert len(_events(app_engine, f, f["case_id"], "case.ai_rerun_requested")) == 1


def test_the_claim_is_taken_once(app_engine, stuck):
    f = stuck
    cid = uuid.UUID(str(f["case_id"]))
    far = datetime.now(UTC) + timedelta(days=1)
    first = ai_rerun.request_rerun(app_engine, f["tid"], cid, trigger="sweeper", now=far)
    second = ai_rerun.request_rerun(app_engine, f["tid"], cid, trigger="staff")
    assert (first, second) == (ai_rerun.STARTED, ai_rerun.ALREADY_RUNNING)


def test_another_escalation_is_409_and_nothing_runs(api, app_engine, flow, fake_runs):
    f = flow
    opened = _open(api, f)
    url = f"/cases/{opened['id']}/rerun-ai"
    assert api.post(url, headers=f["hq"]).status_code == 409  # not escalated at all
    _escalate(app_engine, f, opened["id"], "needs a person")
    assert api.post(url, headers=f["hq"]).status_code == 409
    assert fake_runs == []
    assert _status(app_engine, f, opened["id"]) == "escalated"


def test_customers_get_403_and_other_tenants_404(api, seeded, stuck, fake_runs):
    f = stuck
    assert api.post(f["url"], headers=f["customer"]).status_code == 403
    for cfg in (c for c in seeded.values() if c.slug != f["cfg"].slug):
        for user in (u for u in cfg.users if u.role != "customer"):
            headers = login(api, cfg.slug, user.email)
            assert api.post(f["url"], headers=headers).status_code == 404, user.email
    assert api.post(f"/cases/{uuid.uuid4()}/rerun-ai", headers=f["hq"]).status_code == 404
    assert fake_runs == []


def test_staff_out_of_scope_get_404(api, stuck, fake_runs):
    f = stuck
    for user in (u for u in f["cfg"].users if u.role not in ("customer", "hq_owner")):
        headers = login(api, f["cfg"].slug, user.email)
        if api.get(f"/cases/{f['case_id']}", headers=headers).status_code == 404:
            assert api.post(f["url"], headers=headers).status_code == 404, user.email
    assert fake_runs == []


def test_a_case_escalated_for_a_missing_key_can_be_run_again(api, app_engine, flow, monkeypatch):
    """The real agent path, with the keys missing: the case escalates again for the same
    reason and stays re-runnable (this is how the stuck demo case is cleared, S7.7)."""
    f = flow
    opened = _open(api, f)
    _escalate(app_engine, f, opened["id"], AI_DOWN)
    proposals = _proposals(app_engine, f, opened["id"])

    def no_key(*_a, **_k):
        raise MissingAPIKey("gemini")

    monkeypatch.setattr(agent_runner, "_deps", no_key)
    assert api.post(f"/cases/{opened['id']}/rerun-ai", headers=f["hq"]).status_code == 202
    assert _status(app_engine, f, opened["id"]) == "escalated"
    result = _events(app_engine, f, opened["id"], "case.ai_rerun_result")
    assert [e.payload["outcome"] for e in result] == ["escalated"]
    assert api.get(f"/cases/{opened['id']}", headers=f["hq"]).json()["can_rerun_ai"] is True
    assert _proposals(app_engine, f, opened["id"]) == proposals  # a failed run adds none


def test_the_sweeper_retries_with_backoff_bounded_and_only_when_healthy(
    app_engine, stuck, monkeypatch
):
    f = stuck
    cid = uuid.UUID(str(f["case_id"]))
    runs = []

    def failing_run(engine, tenant_id, case_id, message, pipeline="agents"):
        runs.append(case_id)  # the AI is still down: escalates for the same reason
        graph.escalate_now(engine, tenant_id, case_id, AI_DOWN)
        return {"outcome": "escalated"}

    monkeypatch.setattr(agent_runner, "run_agents", failing_run)
    now = datetime.now(UTC)
    monkeypatch.setattr(agent_runner, "providers_ready", lambda: False)
    assert sweep_tenant(app_engine, f["tid"], now + timedelta(days=1)).ai_reruns == []
    monkeypatch.setattr(agent_runner, "providers_ready", lambda: True)
    # Backoff: too soon after the escalation.
    assert sweep_tenant(app_engine, f["tid"], now + timedelta(minutes=1)).ai_reruns == []
    assert runs == []
    for _ in range(6):  # healthy and due every time, yet bounded
        sweep_tenant(app_engine, f["tid"], now + timedelta(days=10))
    assert runs.count(cid) == ai_rerun.MAX_AUTO_ATTEMPTS
    triggers = [
        e.payload["trigger"] for e in _events(app_engine, f, cid, "case.ai_rerun_requested")
    ]
    assert triggers == ["sweeper"] * ai_rerun.MAX_AUTO_ATTEMPTS
    assert _status(app_engine, f, cid) == "escalated"  # handed back to a person


def test_the_sweeper_leaves_other_escalations_alone(api, app_engine, flow, monkeypatch):
    f = flow
    opened = _open(api, f)
    _escalate(app_engine, f, opened["id"], "needs a person")
    monkeypatch.setattr(agent_runner, "providers_ready", lambda: True)
    monkeypatch.setattr(agent_runner, "run_agents", lambda *a, **k: pytest.fail("ran"))
    report = sweep_tenant(app_engine, f["tid"], datetime.now(UTC) + timedelta(days=10))
    assert opened["id"] not in report.ai_reruns
    assert _status(app_engine, f, opened["id"]) == "escalated"


def _escalate_coded(app_engine, f, case_id, reason, code):
    with tenant_session(f["tid"], app_engine) as s:
        s.execute(update(Case).where(Case.id == uuid.UUID(str(case_id))).values(status="escalated"))
        audit.record(
            s,
            f["tid"],
            actor_type="agent",
            actor_id=None,
            event="case.escalated",
            entity_type="case",
            entity_id=uuid.UUID(str(case_id)),
            payload={"reason": reason, "code": code},
        )


def _no_key(*_a, **_k):
    raise MissingAPIKey("gemini")


def test_eligibility_follows_the_machine_code_not_the_wording(api, app_engine, flow):
    f = flow
    opened = _open(api, f)
    url = f"/cases/{opened['id']}"
    _escalate_coded(app_engine, f, opened["id"], "the models are down", graph.AI_UNAVAILABLE)
    assert api.get(url, headers=f["hq"]).json()["can_rerun_ai"] is True
    _escalate_coded(app_engine, f, opened["id"], "AI unavailable: ProviderFailed", "other")
    assert api.get(url, headers=f["hq"]).json()["can_rerun_ai"] is True  # old-row fallback


def test_the_real_failure_path_writes_the_code(api, app_engine, flow, monkeypatch):
    f = flow
    opened = _open(api, f)
    _escalate(app_engine, f, opened["id"], AI_DOWN)
    monkeypatch.setattr(agent_runner, "_deps", _no_key)
    api.post(f"/cases/{opened['id']}/rerun-ai", headers=f["hq"])
    with tenant_session(f["tid"], app_engine) as s:
        payloads = s.scalars(
            select(AuditEvent.payload).where(
                AuditEvent.event == "case.escalated",
                AuditEvent.entity_id == uuid.UUID(opened["id"]),
            )
        ).all()
    assert any(
        p.get("code") == graph.AI_UNAVAILABLE and "MissingAPIKey" in p["reason"] for p in payloads
    ), payloads


def test_a_stale_sweeper_claim_cannot_start_a_second_run(app_engine, stuck):
    f = stuck
    cid = uuid.UUID(str(f["case_id"]))
    tid = f["tid"]
    now = datetime.now(UTC)
    far = now + timedelta(days=10)

    def claim(trigger, at):
        return ai_rerun.request_rerun(app_engine, tid, cid, trigger=trigger, now=at)

    def run_failed():
        graph.escalate_now(app_engine, tid, cid, AI_DOWN, code=graph.AI_UNAVAILABLE)

    assert claim("sweeper", far) == "started"
    run_failed()
    # A stale 'due' list is acted on again, but the backoff restarted at the new escalation.
    assert claim("sweeper", now + timedelta(minutes=1)) == "not_eligible"
    assert _status(app_engine, f, cid) == "escalated"
    for _ in range(ai_rerun.MAX_AUTO_ATTEMPTS - 1):  # the cap holds even when always due
        assert claim("sweeper", far) == "started"
        run_failed()
    assert claim("sweeper", far) == "not_eligible"
    assert claim("staff", far) == "started"  # a person may still press it


def test_a_skipped_run_hands_the_case_back_with_the_original_reason(
    api, app_engine, stuck, monkeypatch
):
    f = stuck
    monkeypatch.setattr(agent_runner, "run_agents", lambda *a, **k: {"outcome": "skipped"})
    assert api.post(f["url"], headers=f["hq"]).status_code == 202
    assert _status(app_engine, f, f["case_id"]) == "escalated"
    assert api.get(f"/cases/{f['case_id']}", headers=f["hq"]).json()["can_rerun_ai"] is True
    with tenant_session(f["tid"], app_engine) as s:
        last = s.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.event == "case.escalated",
                AuditEvent.entity_id == uuid.UUID(str(f["case_id"])),
            )
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .limit(1)
        ).one()
        assert last.payload["reason"] == AI_DOWN and last.payload["code"] == graph.AI_UNAVAILABLE


def test_a_crash_after_the_claim_leaves_the_case_rerunnable(
    api, app_engine, stuck, fake_runs, monkeypatch
):
    f = stuck
    cid = uuid.UUID(str(f["case_id"]))
    assert ai_rerun.request_rerun(app_engine, f["tid"], cid, trigger="staff") == "started"
    # ...the process dies here: no run, no result. The TTL sweeper escalates the case.
    monkeypatch.setattr(agent_runner, "providers_ready", lambda: False)
    report = sweep_tenant(app_engine, f["tid"], datetime.now(UTC) + timedelta(days=1))
    assert str(cid) in report.escalated_cases
    assert _status(app_engine, f, cid) == "escalated"
    assert api.get(f"/cases/{cid}", headers=f["hq"]).json()["can_rerun_ai"] is True
    assert api.post(f["url"], headers=f["hq"]).json() == {"status": "started"}
    assert len(fake_runs) == 1
