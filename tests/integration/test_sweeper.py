"""The sweeper (E4.5), for every tenant: work a crashed process never did is finished exactly
once with the same stable key, and cases whose agent run died are escalated."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

import app.api.routes_approvals as routes_approvals
import app.api.routes_cases as routes_cases
from app.core.db import tenant_session
from app.core.models import (
    Approval,
    Case,
    Customer,
    Execution,
    LineItem,
    RefundOperation,
    Ticket,
    Transaction,
    User,
    WorkflowRun,
)
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import load_context, tenant_id_for
from app.engine import executor
from app.engine.approvals import decide
from app.engine.graph import RUN_TTL
from app.engine.proposals import create_proposal
from app.engine.sweeper import sweep_tenant
from app.engine.voucher_executor import voucher_key
from mocks.registry import get_mock, merchant_id_for, reset_mocks
from tests.helpers import login


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


@pytest.fixture
def crash_after_commit(monkeypatch):
    """The process dies after the decision commits, before its background task runs."""
    killed = []
    monkeypatch.setattr(routes_approvals, "run_execution", lambda *a: killed.append(a))
    monkeypatch.setattr(routes_cases, "run_execution", lambda *a: killed.append(a))
    return killed


@pytest.fixture
def world(api, app_engine, maint_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    customer = next(u for u in cfg.users if u.role == "customer")
    hq_email = next(u.email for u in cfg.users if u.role == "hq_owner")
    with tenant_session(tid, app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == customer.email))
        customer_id = s.scalar(select(Customer.id).where(Customer.user_id == user_id))
        order = s.scalars(
            select(Transaction)
            .where(Transaction.customer_id == customer_id)
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
        line = s.scalars(
            select(LineItem)
            .where(LineItem.transaction_id == order.id)
            .order_by(LineItem.unit_price_paise.desc())
            .limit(1)
        ).one()
        remedies = tenant_pack(s).remedies
        hq = load_context(s, tid, s.scalar(select(User.id).where(User.email == hq_email)))
        w = {
            "tid": tid,
            "order_id": order.id,
            "customer_id": customer_id,
            "line_id": line.id,
            "qty": line.quantity,
            "missing": line.unit_price_paise,
            "voucher_category": next(c for c, r in remedies.items() if r == "voucher"),
            "refund_category": next(c for c, r in remedies.items() if r == "refund_missing"),
            "hq_ctx": hq,
            "merchant": merchant_id_for(tid),
        }
    w["customer"] = login(api, cfg.slug, customer.email)
    w["hq"] = login(api, cfg.slug, hq_email)
    w_order = w["order_id"]
    yield w
    with tenant_session(tid, app_engine) as s:
        line = s.get(LineItem, w["line_id"])
        line.quantity_fulfilled = w["qty"]
    with tenant_session(tid, maint_engine) as s:
        case_ids = select(Case.id).where(Case.tenant_id == tid, Case.transaction_id == w_order)
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(case_ids)))
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid, RefundOperation.transaction_id == w_order
            )
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.transaction_id == w_order))


def _open(api, w, category):
    resp = api.post(
        "/cases",
        headers=w["customer"],
        json={"transaction_id": str(w["order_id"]), "category": category, "message": "Help."},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sweep(app_engine, w, now=None, **kw):
    # A little ahead of local time: DB timestamps (now()) may be ahead of this machine's clock.
    now = now or datetime.now(UTC) + timedelta(seconds=30)
    return sweep_tenant(app_engine, w["tid"], now=now, min_age=timedelta(0), **kw)


def _ops(kind, w, key):
    """Provider operations for one key (a sweep is tenant-wide; count only ours)."""
    return [op for op in get_mock(kind).operations(w["merchant"]) if op.idempotency_key == key]


def test_a_voucher_killed_after_commit_is_issued_once_by_the_sweeper(
    api, app_engine, world, crash_after_commit
):
    w = world
    opened = _open(api, w, w["voucher_category"])
    assert len(crash_after_commit) == 1  # the task was scheduled, then the process died
    key = voucher_key(uuid.UUID(opened["proposal_id"]))
    assert _ops("vouchers", w, key) == []
    assert api.get(f"/cases/{opened['id']}", headers=w["customer"]).json()["stage"] == (
        "processing"
    )
    assert opened["proposal_id"] in _sweep(app_engine, w).executed
    assert opened["proposal_id"] not in _sweep(app_engine, w).executed  # nothing left to do
    assert len(_ops("vouchers", w, key)) == 1
    assert api.get(f"/cases/{opened['id']}", headers=w["customer"]).json()["stage"] == ("confirmed")


def test_a_refund_killed_after_approval_is_refunded_once_by_the_sweeper(
    api, app_engine, world, crash_after_commit
):
    w = world
    with tenant_session(w["tid"], app_engine) as s:
        s.get(LineItem, w["line_id"]).quantity_fulfilled = w["qty"] - 1
    opened = _open(api, w, w["refund_category"])
    assert opened["action"] == "refund"
    resp = api.post(
        f"/approvals/{opened['proposal_id']}/decision",
        headers=w["hq"],
        json={"decision": "approved"},
    )
    assert resp.status_code == 200 and len(crash_after_commit) == 1
    pid = uuid.UUID(opened["proposal_id"])
    assert _ops("payment", w, executor.refund_key(pid)) == []
    assert str(pid) in _sweep(app_engine, w).executed
    _sweep(app_engine, w)
    assert len(_ops("payment", w, executor.refund_key(pid))) == 1
    assert api.get(f"/cases/{opened['id']}", headers=w["customer"]).json()["stage"] == ("confirmed")


def test_a_crash_between_reserve_and_send_is_resumed_with_the_same_key(app_engine, world):
    """Reserved (money held) but the provider was never called: resume, one refund."""
    w = world
    now = datetime.now(UTC)
    with tenant_session(w["tid"], app_engine) as s:
        case = Case(id=uuid.uuid4(), tenant_id=w["tid"], customer_id=w["customer_id"],
                    transaction_id=w["order_id"], status="awaiting_approval", channel="app",
                    opened_at=now)  # fmt: skip
        s.add(case)
        s.flush()
        pid = create_proposal(
            s,
            w["tid"],
            case_id=case.id,
            action="refund",
            reason="x",
            params={"transaction_id": str(w["order_id"]), "amount_paise": 100, "reason": "x"},
        ).id
        decide(s, w["hq_ctx"], pid, "approved", now)
    job = executor._reserve(app_engine, w["hq_ctx"], pid, now)  # step 2 commits, then: crash
    assert job.fresh and _ops("payment", w, job.key) == []
    report = _sweep(app_engine, w)
    assert str(pid) not in report.executed and str(pid) in report.reconciled
    _sweep(app_engine, w)
    assert len(_ops("payment", w, job.key)) == 1
    with tenant_session(w["tid"], app_engine) as s:
        assert s.scalar(select(Execution.status).where(Execution.proposal_id == pid)) == (
            "succeeded"
        )


def test_a_refund_the_provider_answered_but_nobody_verified_is_verified_by_the_sweeper(
    api, app_engine, world
):
    """The worker died after the executor persisted success, before the verify step: the
    customer is not told "confirmed" without a verdict, and the sweeper supplies it."""
    w = world
    now = datetime.now(UTC)
    with tenant_session(w["tid"], app_engine) as s:
        case = Case(id=uuid.uuid4(), tenant_id=w["tid"], customer_id=w["customer_id"],
                    transaction_id=w["order_id"], status="executing", channel="app",
                    opened_at=now)  # fmt: skip
        s.add(case)
        s.flush()
        case_id = case.id
        pid = create_proposal(
            s,
            w["tid"],
            case_id=case.id,
            action="refund",
            reason="x",
            params={"transaction_id": str(w["order_id"]), "amount_paise": 100, "reason": "x"},
        ).id
        decide(s, w["hq_ctx"], pid, "approved", now)
    assert executor.execute_refund(app_engine, w["hq_ctx"], pid).status == "succeeded"
    stage = lambda: api.get(f"/cases/{case_id}", headers=w["customer"]).json()["stage"]  # noqa: E731
    assert stage() == "processing"  # provider succeeded, no verdict yet
    assert str(pid) in _sweep(app_engine, w).verified
    assert stage() == "confirmed"
    assert str(pid) not in _sweep(app_engine, w).verified  # a final verdict: nothing left
    assert len(_ops("payment", w, executor.refund_key(pid))) == 1


def test_an_expired_approval_is_not_executed_but_escalates_its_case(app_engine, world):
    w = world
    then = datetime.now(UTC) - timedelta(days=2)
    with tenant_session(w["tid"], app_engine) as s:
        case = Case(id=uuid.uuid4(), tenant_id=w["tid"], customer_id=w["customer_id"],
                    transaction_id=w["order_id"], status="awaiting_approval", channel="app",
                    opened_at=then)  # fmt: skip
        s.add(case)
        s.flush()
        case_id = case.id
        pid = create_proposal(
            s,
            w["tid"],
            case_id=case.id,
            action="free_item_voucher",
            reason="x",
            params={"transaction_id": str(w["order_id"]), "value_paise": 100, "reason": "x"},
        ).id
        decide(s, w["hq_ctx"], pid, "approved", then)
    assert str(pid) in _sweep(app_engine, w).executed  # looked at, and refused
    assert _ops("vouchers", w, voucher_key(pid)) == []
    with tenant_session(w["tid"], app_engine) as s:
        assert s.get(Case, case_id).status == "escalated"  # a person owns it now
    assert str(pid) not in _sweep(app_engine, w).executed  # and it is not picked up again


def _approved_proposal(app_engine, w, action, params, status="executing"):
    now = datetime.now(UTC)
    with tenant_session(w["tid"], app_engine) as s:
        case = Case(id=uuid.uuid4(), tenant_id=w["tid"], customer_id=w["customer_id"],
                    transaction_id=w["order_id"], status=status, channel="app",
                    opened_at=now)  # fmt: skip
        s.add(case)
        s.flush()
        case_id = case.id
        pid = create_proposal(
            s, w["tid"], case_id=case_id, action=action, reason="x",
            params={"transaction_id": str(w["order_id"]), "reason": "x", **params},
        ).id  # fmt: skip
        decide(s, w["hq_ctx"], pid, "approved", now)
    return case_id, pid


def test_one_failing_proposal_does_not_stop_the_rest_of_the_sweep(app_engine, world, monkeypatch):
    import app.engine.sweeper as sweeper

    w = world
    _, bad = _approved_proposal(app_engine, w, "refund", {"amount_paise": 100})
    _, good = _approved_proposal(app_engine, w, "free_item_voucher", {"value_paise": 100})
    stuck = _investigating_case(app_engine, w, RUN_TTL * 2)
    real = sweeper.run_approved

    def flaky(engine, tenant_id, proposal_id, action):
        if proposal_id == bad:
            raise RuntimeError("provider exploded")
        return real(engine, tenant_id, proposal_id, action)

    monkeypatch.setattr(sweeper, "run_approved", flaky)
    called = []
    monkeypatch.setattr(sweeper, "prune_finished", lambda *a: called.append("prune") or 0)
    report = _sweep(app_engine, w, run_ttl=timedelta(seconds=1))
    assert str(good) in report.executed and len(_ops("vouchers", w, voucher_key(good))) == 1
    assert _ops("payment", w, executor.refund_key(bad)) == []
    assert str(stuck) in report.escalated_cases and called == ["prune"]  # the rest still ran


def test_a_refund_that_was_never_sent_gets_a_final_verdict_once(app_engine, world):
    """Refused before sending: the provider has no record, which is the expected final state
    (not "unknown" on every sweep forever)."""
    from app.core.models import Verification

    w = world
    _, pid = _approved_proposal(app_engine, w, "refund", {"amount_paise": 100})
    with tenant_session(w["tid"], app_engine) as s:
        approval_id = s.scalar(select(Approval.id).where(Approval.proposal_id == pid))
        s.add(Execution(tenant_id=w["tid"], proposal_id=pid, approval_id=approval_id,
                        idempotency_key=executor.refund_key(pid), status="failed",
                        error="refused: not_eligible: x"))  # fmt: skip
    assert str(pid) in _sweep(app_engine, w).verified
    assert str(pid) not in _sweep(app_engine, w).verified
    with tenant_session(w["tid"], app_engine) as s:
        verdicts = s.scalars(
            select(Verification.status).join(Execution).where(Execution.proposal_id == pid)
        ).all()
    assert verdicts == ["verified"] and _ops("payment", w, executor.refund_key(pid)) == []


def test_a_paused_run_whose_proposal_the_sweeper_finished_is_completed(app_engine, world):
    w = world
    case_id, pid = _approved_proposal(
        app_engine, w, "free_item_voucher", {"value_paise": 100}, status="awaiting_approval"
    )
    with tenant_session(w["tid"], app_engine) as s:
        s.add(WorkflowRun(tenant_id=w["tid"], case_id=case_id, status="paused"))
    assert str(pid) in _sweep(app_engine, w).executed  # no checkpoint to resume: direct path
    with tenant_session(w["tid"], app_engine) as s:
        runs = s.scalars(select(WorkflowRun.status).where(WorkflowRun.case_id == case_id)).all()
    assert runs == ["completed"]  # so it can be pruned, not left paused forever


def _investigating_case(app_engine, w, run_age):
    with tenant_session(w["tid"], app_engine) as s:
        case = Case(id=uuid.uuid4(), tenant_id=w["tid"], customer_id=w["customer_id"],
                    transaction_id=w["order_id"], status="investigating", channel="app",
                    opened_at=datetime.now(UTC))  # fmt: skip
        s.add(case)
        s.flush()
        if run_age is not None:
            s.add(WorkflowRun(tenant_id=w["tid"], case_id=case.id, status="running",
                              created_at=datetime.now(UTC) - run_age))  # fmt: skip
        return case.id


@pytest.mark.parametrize("run_age", [RUN_TTL * 2, None], ids=["dead_run", "never_started"])
def test_a_case_whose_agent_run_died_is_escalated(app_engine, world, run_age):
    w = world
    case_id = _investigating_case(app_engine, w, run_age)
    assert str(case_id) not in _sweep(app_engine, w).escalated_cases  # within the TTL
    later = datetime.now(UTC) + RUN_TTL + timedelta(minutes=1)
    assert str(case_id) in _sweep(app_engine, w, now=later).escalated_cases
    with tenant_session(w["tid"], app_engine) as s:
        assert s.get(Case, case_id).status == "escalated"
        runs = s.scalars(select(WorkflowRun.status).where(WorkflowRun.case_id == case_id)).all()
        assert "running" not in runs
    assert str(case_id) not in _sweep(app_engine, w, now=later).escalated_cases


def test_a_live_run_is_left_alone(app_engine, world):
    w = world
    # Seen from `later`: the case row is older than the TTL, but its run started within it.
    case_id = _investigating_case(app_engine, w, -timedelta(minutes=2))
    later = datetime.now(UTC) + timedelta(minutes=3)
    report = _sweep(app_engine, w, now=later, run_ttl=timedelta(minutes=2))
    assert str(case_id) not in report.escalated_cases
    with tenant_session(w["tid"], app_engine) as s:
        assert s.get(Case, case_id).status == "investigating"
