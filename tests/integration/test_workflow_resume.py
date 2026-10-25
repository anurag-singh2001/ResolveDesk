# ruff: noqa: F811 (pytest fixtures imported from test_agent_graph)
"""E4.1/E4.2: the graph pauses at `approve` (interrupt + Postgres checkpoint), resumes on the
decision - also in a new process - executes, verifies, and tells the customer only verified
facts. Also: rejection, expiry, auto-approval without a pause, the customer-reply resume, and
the verifier's mismatch path. For every tenant (scripted LLMs; no tenant is named)."""

import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

import app.engine.graph as graph
from app.api import routes_cases
from app.config import get_settings
from app.connectors.base import RefundOutcome
from app.connectors.mock_connectors import MockPaymentConnector
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    DomainEvent,
    Execution,
    Ticket,
    TicketMessage,
    User,
    Verification,
    WorkflowRun,
)
from app.core.tenancy import load_context
from app.engine import agent_runner, lifecycle
from app.engine.approvals import decide
from app.engine.case_status import case_status
from app.engine.checkpoint import open_checkpointer, thread_config
from mocks.registry import get_mock, merchant_id_for, reset_mocks
from tests.helpers import login
from tests.integration.test_agent_graph import (  # noqa: F401 (fixtures)
    EMBEDDER,
    NOW,
    FakeBudget,
    FakeLLM,
    _classify,
    _refund,
    case,
    policies_loaded,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


@pytest.fixture
def hq(app_engine, policies_loaded, tenant, case):  # noqa: F811
    cfg = policies_loaded[tenant.name]
    email = next(u.email for u in cfg.users if u.role == "hq_owner")
    with tenant_session(case["tid"], app_engine) as s:
        return load_context(s, case["tid"], s.scalar(select(User.id).where(User.email == email)))


def _deps(app_engine, clf=None, res=None, now=NOW):
    return graph.Deps(app_engine, clf, res, EMBEDDER, now=now)


def _paused_refund(app_engine, case):  # noqa: F811
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    out = graph.run_case(_deps(app_engine, clf, res), case["tid"], case["case_id"],
                         "One item was missing from my order.", FakeBudget([clf, res]))  # fmt: skip
    assert out["outcome"] == "proposed" and out["paused"], out.get("reason")
    return uuid.UUID(out["proposal_id"]), uuid.UUID(out["run_id"])


def _decide(app_engine, case, hq, pid, decision, now=NOW):  # noqa: F811
    with tenant_session(case["tid"], app_engine) as s:
        decide(s, hq, pid, decision, now)


def _state(app_engine, case, pid=None, run_id=None):  # noqa: F811
    with tenant_session(case["tid"], app_engine) as s:
        c = s.get(Case, case["case_id"])
        execution = s.scalar(select(Execution).where(Execution.proposal_id == pid)) if pid else None
        verdicts = (
            list(
                s.scalars(
                    select(Verification.status).where(Verification.execution_id == execution.id)
                )
            )  # fmt: skip
            if execution
            else []
        )
        updates = list(
            s.scalars(
                select(TicketMessage.body)
                .join(Ticket)
                .where(Ticket.case_id == c.id, TicketMessage.author == "system")
                .order_by(TicketMessage.sent_at)
            )
        )
        events = set(s.scalars(select(DomainEvent.event).where(DomainEvent.entity_id == c.id)))
        return {
            "status": c.status,
            "stage": case_status(s, c).stage,
            "execution": execution.status if execution else None,
            "verifications": verdicts,
            "updates": updates,
            "events": events,
            "run": s.get(WorkflowRun, run_id).status if run_id else None,
        }


def _ops(case):  # noqa: F811
    return get_mock("payment").operations(merchant_id_for(case["tid"]))


def test_refund_pauses_with_a_checkpoint_and_waits_for_a_person(app_engine, case):  # noqa: F811
    pid, run_id = _paused_refund(app_engine, case)
    with open_checkpointer(app_engine) as saver:  # a fresh connection sees the checkpoint
        snap = graph.build_graph(_deps(app_engine), saver).get_state(
            thread_config(case["tid"], case["case_id"])
        )
    assert snap.next == ("approve",)
    assert graph._pending(snap, "approval") == {"kind": "approval", "proposal_id": str(pid)}
    st = _state(app_engine, case, pid, run_id)
    assert (st["status"], st["stage"], st["run"]) == ("awaiting_approval", "awaiting_approval",
                                                      "paused")  # fmt: skip
    assert _ops(case) == []
    # Waking it without a decision changes nothing: the decision is read from the database.
    out = graph.resume_case(_deps(app_engine), case["tid"], case["case_id"], "approval",
                            {"proposal_id": str(pid), "decision": "approved"})  # fmt: skip
    assert out["paused"] and _ops(case) == []
    assert _state(app_engine, case, pid)["execution"] is None


def test_approval_resumes_after_a_process_restart(app_engine, case, hq):  # noqa: F811
    """The decision lands, then a brand-new process (no shared memory) resumes the thread
    from the Postgres checkpoint: execute, verify, resolved."""
    pid, run_id = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    script = (
        "import sys, uuid\n"
        "from sqlalchemy import create_engine\n"
        "from app.config import get_settings\n"
        "from app.core.db import ENGINE_OPTIONS\n"
        "from app.engine.agent_runner import after_decision\n"
        "from mocks.registry import get_mock, merchant_id_for\n"
        "e = create_engine(get_settings().test_database_url, **ENGINE_OPTIONS)\n"
        "t, c, p = (uuid.UUID(a) for a in sys.argv[1:4])\n"
        "out = after_decision(e, t, c, p, True)\n"
        "print(out['outcome'], out.get('paused'), len(get_mock('payment').operations("
        "merchant_id_for(t))))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(case["tid"]), str(case["case_id"]), str(pid)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.split()[-3:] == ["resolved", "False", "1"], proc.stdout
    st = _state(app_engine, case, pid, run_id)
    assert (st["status"], st["stage"], st["execution"], st["run"]) == (
        "resolved", "confirmed", "succeeded", "completed")  # fmt: skip
    assert st["verifications"] == ["verified"]
    assert "has been processed by our payment provider" in st["updates"][-1]
    assert {"case.proposed", "case.approved", "case.executed", "case.verified"} <= st["events"]


def test_rejection_ends_the_thread_declined(app_engine, case, hq):  # noqa: F811
    pid, run_id = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "rejected")
    out = agent_runner.after_decision(app_engine, case["tid"], case["case_id"], pid, False)
    assert out["outcome"] == "declined" and not out["paused"]
    st = _state(app_engine, case, pid, run_id)
    assert (st["status"], st["stage"], st["execution"], st["run"]) == (
        "closed", "declined", None, "completed")  # fmt: skip
    assert st["updates"][-1] == "Your request was reviewed and not approved."
    assert "case.rejected" in st["events"] and _ops(case) == []


def test_an_approval_that_expired_before_execution_escalates(app_engine, case, hq):  # noqa: F811
    pid, run_id = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    with tenant_session(case["tid"], app_engine) as s:
        expires = s.scalar(select(Approval.expires_at).where(Approval.proposal_id == pid))
    later = _deps(app_engine, now=expires + timedelta(seconds=1))
    out = graph.resume_case(later, case["tid"], case["case_id"], "approval", {})
    assert out["outcome"] == "escalated" and _ops(case) == []  # nothing sent
    st = _state(app_engine, case, pid, run_id)
    assert (st["status"], st["stage"], st["execution"]) == ("escalated", "escalated", None)
    assert "case.escalated" in st["events"]
    assert "processed" not in st["updates"][-1]  # never claims money moved


def test_a_provider_mismatch_escalates_instead_of_confirming(app_engine, case, hq, monkeypatch):  # noqa: F811
    pid, run_id = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    real = MockPaymentConnector.find_refund

    def wrong_amount(self, ctx, key):
        found = real(self, ctx, key)
        return RefundOutcome(found.status, found.provider_reference, None, found.amount_paise + 1)

    monkeypatch.setattr(MockPaymentConnector, "find_refund", wrong_amount)
    out = agent_runner.after_decision(app_engine, case["tid"], case["case_id"], pid, True)
    assert out["outcome"] == "escalated"
    st = _state(app_engine, case, pid, run_id)
    assert (st["status"], st["stage"], st["execution"]) == ("escalated", "escalated", "succeeded")
    assert st["verifications"] == ["mismatch"]
    assert "case.verified" not in st["events"] and "case.escalated" in st["events"]


def test_a_timeout_is_processing_until_reconciled_and_verified(app_engine, case, hq):  # noqa: F811
    from mocks.base import Chaos

    pid, _ = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    get_mock("payment").set_chaos(Chaos(accept_then_timeout_rate=1.0), merchant_id_for(case["tid"]))
    out = agent_runner.after_decision(app_engine, case["tid"], case["case_id"], pid, True)
    assert out["outcome"] == "processing"
    st = _state(app_engine, case, pid)
    assert (st["stage"], st["execution"], st["verifications"]) == ("processing", "unknown", [])
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(case["tid"]))
    assert lifecycle.reconcile_and_verify(app_engine, case["tid"], pid) == "resolved"
    st = _state(app_engine, case, pid)
    assert (st["status"], st["stage"], st["verifications"]) == ("resolved", "confirmed",
                                                                ["verified"])  # fmt: skip
    assert len(_ops(case)) == 1


def test_an_auto_approved_proposal_continues_without_pausing(app_engine, case, monkeypatch):  # noqa: F811
    """Auto-approval is code's rule; when it approves, the graph never interrupts."""
    real = lifecycle.auto_decide

    def approve_by_rule(session, tenant_id, proposal_id, now):
        approval = real(session, tenant_id, proposal_id, now)
        if approval is None:  # stand-in rule for this test: approve it as "auto"
            proposal = session.get(ActionProposal, proposal_id)
            approval = Approval(tenant_id=tenant_id, proposal_id=proposal_id,
                                payload_hash=proposal.payload_hash, decision="approved",
                                mode="auto", decided_at=now,
                                expires_at=now + timedelta(minutes=30))  # fmt: skip
            session.add(approval)
            session.flush()
        return approval

    monkeypatch.setattr(lifecycle, "auto_decide", approve_by_rule)
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    out = graph.run_case(_deps(app_engine, clf, res), case["tid"], case["case_id"],
                         "One item was missing.", FakeBudget([clf, res]))  # fmt: skip
    assert out["outcome"] == "resolved" and not out["paused"], out
    st = _state(app_engine, case, uuid.UUID(out["proposal_id"]), uuid.UUID(out["run_id"]))
    assert (st["stage"], st["run"]) == ("confirmed", "completed")


def test_a_customer_reply_resumes_a_case_waiting_for_info(
    api,
    app_engine,
    case,
    policies_loaded,
    tenant,
    monkeypatch,  # noqa: F811
):
    clf = FakeLLM({"Classification": [_classify(needs=["which item"]), _classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    first = graph.run_case(_deps(app_engine, clf, res), case["tid"], case["case_id"],
                           "Something was wrong.", FakeBudget([clf, res]))  # fmt: skip
    assert first["outcome"] == "awaiting_info" and first["paused"]
    monkeypatch.setattr(agent_runner, "_deps", lambda engine, budget: _deps(engine, clf, res))
    agents = get_settings().model_copy(update={"engine_mode": "agents"})  # free-text replies
    monkeypatch.setattr(routes_cases, "get_settings", lambda: agents)
    cfg = policies_loaded[tenant.name]
    customer = login(api, cfg.slug, next(u.email for u in cfg.users if u.role == "customer"))
    body = {"transaction_id": str(case["order_id"]), "message": "The costliest item was missing."}
    reply = api.post("/cases", headers=customer, json=body)
    assert reply.status_code == 201 and reply.json()["id"] == str(case["case_id"])
    assert "The costliest item was missing." in clf.calls[1][1][-1].content  # the reply reached it
    st = _state(app_engine, case, run_id=uuid.UUID(first["run_id"]))
    assert (st["status"], st["stage"], st["run"]) == ("awaiting_approval", "awaiting_approval",
                                                      "paused")  # fmt: skip
    # A second resume of the same pause is refused (the thread moved on).
    again = graph.resume_case(_deps(app_engine, clf, res), case["tid"], case["case_id"], "info",
                              {"message": "again"})  # fmt: skip
    assert again["outcome"] == "skipped"


def test_a_decision_before_the_run_is_marked_paused_still_executes(app_engine, case, hq):
    """Race: the decision lands while the first pass hasn't recorded 'paused' yet. The resume
    is refused (run still 'running'), so the idempotent code path runs it instead."""
    pid, run_id = _paused_refund(app_engine, case)
    with tenant_session(case["tid"], app_engine) as s:
        s.get(WorkflowRun, run_id).status = "running"
    _decide(app_engine, case, hq, pid, "approved")
    out = agent_runner.after_decision(app_engine, case["tid"], case["case_id"], pid, True)
    assert out["outcome"] == "resolved"
    assert _state(app_engine, case, pid)["stage"] == "confirmed" and len(_ops(case)) == 1


def test_another_tenants_id_cannot_resume_the_thread(app_engine, case, hq):
    pid, _ = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    other = uuid.uuid4()  # not this case's tenant: RLS hides the case, the thread id differs
    out = graph.resume_case(_deps(app_engine), other, case["case_id"], "approval", {})
    assert out["outcome"] == "skipped" and _ops(case) == []
    assert _state(app_engine, case, pid)["execution"] is None


def test_a_failed_subscriber_leaves_the_event_for_redelivery(app_engine, case, monkeypatch):
    from app.core import events

    calls = []

    def flaky(session, event):
        calls.append(event.id)
        if len(calls) == 1:
            raise RuntimeError("subscriber down")

    monkeypatch.setitem(events._SUBSCRIBERS, "test.retry", [flaky])
    with tenant_session(case["tid"], app_engine) as s:
        event_id = events.emit(s, case["tid"], "test.retry", case["case_id"]).id
    with tenant_session(case["tid"], app_engine) as s:
        assert s.get(DomainEvent, event_id).published_at is None  # the state change committed
    assert events.publish_pending(app_engine, case["tid"]) >= 1
    with tenant_session(case["tid"], app_engine) as s:
        assert s.get(DomainEvent, event_id).published_at is not None
    assert calls.count(event_id) == 2
