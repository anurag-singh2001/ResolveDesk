# ruff: noqa: F811 (pytest fixtures imported from test_agent_graph)
"""E4.1/E4.2: the graph pauses at `approve` (interrupt + Postgres checkpoint), resumes on the
decision - also in a new process - executes, verifies, and tells the customer only verified
facts. Also: rejection, expiry, auto-approval without a pause, the customer-reply resume, and
the verifier's mismatch path. For every tenant (scripted LLMs; no tenant is named)."""

import json
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

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


# ---- Checkpoint guards (human sign-off 2026-10-26, DECISIONS.md): ids and codes only, thread
# ---- ownership, no API over `lg`, pruning of finished runs. ----


def _lg_text(app_engine, case):  # noqa: F811
    """Everything stored for this case's thread, as one searchable bytes string."""
    thread = f"{case['tid']}:{case['case_id']}"
    chunks = []
    with app_engine.connect() as conn:
        queries = [
            "SELECT checkpoint::text, metadata::text FROM lg.checkpoints WHERE thread_id = :t",
            "SELECT blob FROM lg.checkpoint_blobs WHERE thread_id = :t",
            "SELECT blob FROM lg.checkpoint_writes WHERE thread_id = :t",
        ]
        for q in queries:
            for row in conn.execute(text(q), {"t": thread}):
                chunks += [bytes(v) if isinstance(v, memoryview | bytes) else str(v).encode()
                           for v in row if v]  # fmt: skip
    return b"\n".join(chunks)


def _lg_rows(app_engine, case):  # noqa: F811
    with app_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM lg.checkpoints WHERE thread_id = :t"),
            {"t": f"{case['tid']}:{case['case_id']}"},
        ).scalar()


def test_checkpoints_hold_ids_and_codes_not_customer_data(app_engine, case):  # noqa: F811
    secret = "ZEBRA-QUOKKA-7731 my order was wrong"
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    out = graph.run_case(_deps(app_engine, clf, res), case["tid"], case["case_id"], secret,
                         FakeBudget([clf, res]))  # fmt: skip
    assert out["paused"] and _lg_rows(app_engine, case) > 0
    stored = _lg_text(app_engine, case)
    assert str(case["case_id"]).encode() in stored  # it does hold ids
    assert b"ZEBRA-QUOKKA" not in stored
    assert out["reason"].encode() not in stored  # the model's reason
    assert out["citations"] and all(c["text"][:40].encode() not in stored for c in out["citations"])
    assert json.dumps(out["evidence"]["order"]["items"][0]).encode() not in stored


def test_a_waiting_for_info_checkpoint_has_no_message_either(app_engine, case):  # noqa: F811
    secret = "ZEBRA-QUOKKA-9912 something odd"
    clf = FakeLLM({"Classification": [_classify(needs=["which item"])]})
    out = graph.run_case(_deps(app_engine, clf, FakeLLM({})), case["tid"], case["case_id"],
                         secret, FakeBudget([clf]))  # fmt: skip
    assert out["outcome"] == "awaiting_info" and out["paused"]
    stored = _lg_text(app_engine, case)
    assert stored and b"ZEBRA-QUOKKA" not in stored


def test_a_forged_thread_of_another_tenant_cannot_be_resumed(app_engine, case, hq):  # noqa: F811
    pid, _ = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    other = uuid.uuid4()
    real, forged = f"{case['tid']}:{case['case_id']}", f"{other}:{case['case_id']}"
    with app_engine.begin() as conn:  # a planted copy of the thread under the other tenant id
        for t in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            conn.execute(text(f"UPDATE lg.{t} SET thread_id = :f WHERE thread_id = :r"),
                         {"f": forged, "r": real})  # fmt: skip
    out = graph.resume_case(_deps(app_engine), other, case["case_id"], "approval", {})
    assert out["outcome"] == "skipped" and _ops(case) == []
    assert _state(app_engine, case, pid)["execution"] is None


def test_a_thread_whose_stored_tenant_differs_is_refused(app_engine, case, hq):  # noqa: F811
    pid, _ = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    config = thread_config(case["tid"], case["case_id"])
    with open_checkpointer(app_engine) as saver:
        graph.build_graph(_deps(app_engine), saver).update_state(
            config,
            {"tenant_id": str(uuid.uuid4())},  # the state claims another tenant
        )
    out = graph.resume_case(_deps(app_engine), case["tid"], case["case_id"], "approval", {})
    assert out["outcome"] == "skipped" and _ops(case) == []
    assert _state(app_engine, case, pid)["execution"] is None


def test_finished_runs_leave_no_checkpoints(app_engine, case, hq):  # noqa: F811
    pid, _ = _paused_refund(app_engine, case)
    assert _lg_rows(app_engine, case) > 0  # paused: kept
    _decide(app_engine, case, hq, pid, "approved")
    out = agent_runner.after_decision(app_engine, case["tid"], case["case_id"], pid, True)
    assert out["outcome"] == "resolved" and not out["paused"]
    assert _lg_rows(app_engine, case) == 0  # finished: pruned


def test_prune_finished_deletes_only_finished_threads(app_engine, case):  # noqa: F811
    _, run_id = _paused_refund(app_engine, case)
    graph.prune_finished(app_engine, case["tid"])
    assert _lg_rows(app_engine, case) > 0  # its run is paused: kept
    with tenant_session(case["tid"], app_engine) as s:
        s.get(WorkflowRun, run_id).status = "escalated"
    assert graph.prune_finished(app_engine, case["tid"]) >= 1
    assert _lg_rows(app_engine, case) == 0


def test_a_crash_after_execution_does_not_escalate_or_prune(app_engine, case, hq, monkeypatch):  # noqa: F811
    pid, run_id = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")

    def boom(*a, **k):
        raise RuntimeError("verify crashed")

    monkeypatch.setattr(lifecycle, "verify_executed", boom)
    out = agent_runner.after_decision(app_engine, case["tid"], case["case_id"], pid, True)
    assert out["outcome"] == "processing" and not out["paused"]
    st = _state(app_engine, case, pid, run_id)
    assert st["execution"] is not None  # the money step happened
    assert st["status"] == "executing"  # left for reconcile/verify, not escalated
    assert "case.escalated" not in st["events"]
    assert _lg_rows(app_engine, case) > 0  # thread kept


def test_verifying_never_overwrites_a_case_a_person_already_closed(app_engine, case, hq):  # noqa: F811
    pid, _ = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    assert lifecycle.execute_approved(app_engine, case["tid"], pid, NOW) == "executed"
    with tenant_session(case["tid"], app_engine) as s:
        s.get(Case, case["case_id"]).status = "closed"  # a person closed it meanwhile
    assert lifecycle.verify_executed(app_engine, case["tid"], pid) == "resolved"
    st = _state(app_engine, case, pid)
    assert st["verifications"] == ["verified"]  # the verdict is recorded
    assert st["status"] == "closed"  # but the case is left as the person set it


def test_a_decision_that_lands_before_paused_is_recorded_completes_the_run(
    app_engine,
    case,
    hq,
    monkeypatch,  # noqa: F811
):
    real = graph._invoke

    def racing(deps, saver, tid, cid, payload, build):
        result = real(deps, saver, tid, cid, payload, build)
        _decide(app_engine, case, hq, uuid.UUID(result[0]["proposal_id"]), "approved")
        return result  # the first pass is about to record 'paused'

    monkeypatch.setattr(graph, "_invoke", racing)
    clf = FakeLLM({"Classification": [_classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    out = graph.run_case(_deps(app_engine, clf, res), case["tid"], case["case_id"],
                         "One item was missing.", FakeBudget([clf, res]))  # fmt: skip
    pid, run_id = uuid.UUID(out["proposal_id"]), uuid.UUID(out["run_id"])
    assert not out["paused"]
    assert _state(app_engine, case, pid, run_id)["run"] == "completed"
    assert _lg_rows(app_engine, case) == 0
    monkeypatch.setattr(graph, "_invoke", real)
    done = agent_runner.after_decision(app_engine, case["tid"], case["case_id"], pid, True)
    assert done["outcome"] == "resolved" and len(_ops(case)) == 1  # the code path ran it once


def test_a_staff_approval_of_a_paused_case_executes_once_even_if_both_paths_fire(  # noqa: F811
    app_engine, case, hq
):
    """One execution path: the decision task resumes the paused graph (its execute node) and
    the dispatch fallback also fires (a retry, the sweeper, a second worker). One approval,
    one stable key, so exactly one provider operation and one verdict - in either order and
    even when they overlap."""
    from concurrent.futures import ThreadPoolExecutor

    from app.api import routes_approvals
    from app.engine.dispatch import run_approved

    pid, run_id = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "approved")
    tid, cid = case["tid"], case["case_id"]

    def resume():  # what the decision route's task does first
        return agent_runner.resume_after_decision(app_engine, tid, cid, pid)

    def fallback():  # the second entry into the same path
        return run_approved(app_engine, tid, pid, "refund")

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(resume), pool.submit(fallback)]
        [j.result() for j in jobs]
    fallback()  # and once more after both finished: still a no-op
    routes_approvals._after_decision(app_engine, hq, cid, pid, "refund", True)

    assert len(_ops(case)) == 1  # one provider operation
    st = _state(app_engine, case, pid, run_id)
    assert (st["status"], st["stage"], st["execution"]) == ("resolved", "confirmed", "succeeded")
    assert st["verifications"] == ["verified"]


def test_a_closed_case_survives_a_failed_resume_unchanged(app_engine, case, hq, monkeypatch):  # noqa: F811
    """Staff rejected (case closed) and the resume then blew up: the failure handler must not
    flip the closed case to escalated, nor add an audit row, event or customer message."""
    pid, run_id = _paused_refund(app_engine, case)
    _decide(app_engine, case, hq, pid, "rejected")
    before = _state(app_engine, case, pid, run_id)
    assert before["status"] == "closed"

    def boom(*a, **k):
        raise RuntimeError("connection dropped")

    monkeypatch.setattr(graph, "_invoke", boom)
    agent_runner.resume_after_decision(app_engine, case["tid"], case["case_id"], pid)
    graph.escalate_now(app_engine, case["tid"], case["case_id"], "late escalation")
    after = _state(app_engine, case, pid, run_id)
    assert after["status"] == "closed" and "case.escalated" not in after["events"]
    assert after["updates"] == before["updates"] and after["events"] == before["events"]


def test_a_paused_voucher_resumes_through_execute_and_verify(app_engine, case, hq, monkeypatch):  # noqa: F811
    """A voucher that waits for a person: the resume runs execute -> verify_executed; the case
    is resolved after the provider confirms and `case.verified` is emitted once only."""
    from app.core.models import DomainEvent
    from tests.integration.test_agent_graph import _voucher, _voucher_ceiling

    monkeypatch.setattr(lifecycle, "auto_decide", lambda *a, **k: None)  # never auto-approve
    category, ceiling = _voucher_ceiling(app_engine, case)
    clf = FakeLLM({"Classification": [_classify(category)]})
    res = FakeLLM({"ResolutionDraft": [_voucher(case, ceiling.params["value_paise"])]})
    out = graph.run_case(_deps(app_engine, clf, res), case["tid"], case["case_id"],
                         "Wrong order.", FakeBudget([clf, res]))  # fmt: skip
    assert out["outcome"] == "proposed" and out["paused"], out.get("reason")
    pid = uuid.UUID(out["proposal_id"])
    _decide(app_engine, case, hq, pid, "approved")
    done = agent_runner.resume_after_decision(app_engine, case["tid"], case["case_id"], pid)
    assert done["outcome"] == "resolved", done
    assert lifecycle.verify_executed(app_engine, case["tid"], pid) == "resolved"  # again
    st = _state(app_engine, case, pid)
    assert (st["status"], st["stage"], st["execution"]) == ("resolved", "confirmed", "succeeded")
    assert len(get_mock("vouchers").operations(merchant_id_for(case["tid"]))) == 1
    with tenant_session(case["tid"], app_engine) as s:
        verified = s.scalars(
            select(DomainEvent.id).where(
                DomainEvent.entity_id == case["case_id"], DomainEvent.event == "case.verified"
            )
        ).all()
    assert len(verified) == 1


def test_no_api_route_exposes_checkpoint_data(monkeypatch):
    from app.main import create_app

    paths = " ".join(getattr(r, "path", "") for r in create_app().routes).lower()
    assert "checkpoint" not in paths and "/lg" not in paths and "thread" not in paths
