"""Safe refund execution end to end (PROJECT.md section 10), for every tenant.

Done-when (E2.3b): a refund resolves with no LLM; over-refund, expired approval and a changed
payload are all blocked; no path creates two provider operations for one proposal.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    DomainEvent,
    Execution,
    Payment,
    RefundOperation,
    Transaction,
    User,
)
from app.core.money import percent_of
from app.core.tenancy import load_context, tenant_id_for
from app.engine.approvals import AlreadyDecided, NotEligible, NotFound, auto_decide, decide
from app.engine.eligibility import order_facts
from app.engine.executor import ExecutionRefused, execute_refund, reconcile_refund, refund_key
from app.engine.proposals import create_proposal
from mocks.base import Chaos
from mocks.registry import get_mock, merchant_id_for, reset_mocks

NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


@pytest.fixture
def world(app_engine, maint_engine, seeded_history, tenant):
    """A case on one order, plus the tenant's hq owner context. Cleaned up as maintenance."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    hq_email = next(u.email for u in cfg.users if u.role == "hq_owner")
    with tenant_session(tid, app_engine) as s:
        order = s.scalars(
            select(Transaction).order_by(Transaction.total_paise.desc(), Transaction.id).limit(1)
        ).one()
        hq = load_context(s, tid, s.scalar(select(User.id).where(User.email == hq_email)))
        case_id = uuid.uuid4()
        s.add(
            Case(
                id=case_id,
                tenant_id=tid,
                customer_id=order.customer_id,
                transaction_id=order.id,
                status="open",
                channel="app",
                opened_at=NOW,
            )
        )
        _, facts = order_facts(s, order.id)
        # Read everything needed before the session commits (instances expire on commit).
        w = {
            "cfg": cfg,
            "tid": tid,
            "hq": hq,
            "case_id": case_id,
            "order_id": order.id,
            "total": order.total_paise,
            "settings": facts.settings,
            "cap": percent_of(order.total_paise, facts.settings["refund_max_percent"]),
        }
    yield w
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid, RefundOperation.transaction_id == w["order_id"]
            )
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id == case_id))


def propose(app_engine, w, amount):
    with tenant_session(w["tid"], app_engine) as s:
        p = create_proposal(
            s,
            w["hq"].tenant_id,
            case_id=w["case_id"],
            action="refund",
            reason="policy",
            params={
                "transaction_id": str(w["order_id"]),
                "amount_paise": amount,
                "reason": "late delivery",
            },
        )
        return p.id


def approve(app_engine, w, proposal_id, ctx=None, now=NOW, decision="approved"):
    with tenant_session(w["tid"], app_engine) as s:
        decide(s, ctx or w["hq"], proposal_id, decision, now)


def provider_ops(w):
    return get_mock("payment").operations(merchant_id_for(w["tid"]))


def ledger(app_engine, w):
    with tenant_session(w["tid"], app_engine) as s:
        return s.execute(
            select(
                RefundOperation.proposal_id, RefundOperation.status, RefundOperation.amount_paise
            ).where(RefundOperation.transaction_id == w["order_id"])
        ).all()


def small(w):
    return max(1, min(w["cap"], w["settings"]["refund_without_escalation_paise"]) // 2)


# --- happy path --------------------------------------------------------------------------


def test_approved_refund_succeeds_once(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    result = execute_refund(app_engine, w["hq"], pid)
    assert result.status == "succeeded" and result.idempotency_key == refund_key(pid)
    (op,) = provider_ops(w)
    assert op.request.amount_paise == small(w)
    assert [(r.status, r.amount_paise) for r in ledger(app_engine, w)] == [("succeeded", small(w))]
    with tenant_session(w["tid"], app_engine) as s:
        events = set(s.scalars(select(AuditEvent.event).where(AuditEvent.entity_id == pid)))
        assert {"approval.approved", "refund.reserved", "refund.succeeded"} <= events
        assert (
            s.scalar(
                select(func.count()).select_from(DomainEvent).where(DomainEvent.entity_id == pid)
            )
            == 1
        )


def test_running_again_returns_the_same_result_without_a_second_call(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    first = execute_refund(app_engine, w["hq"], pid)
    assert execute_refund(app_engine, w["hq"], pid) == first
    assert len(provider_ops(w)) == 1


# --- blocked -------------------------------------------------------------------------------


def test_over_refund_is_blocked(app_engine, world):
    """Approved proposals that together exceed what was paid: the later one is refused."""
    w = world
    pids, remaining = [], w["total"]
    while remaining > 0:
        amount = min(w["cap"], remaining)
        pid = propose(app_engine, w, amount)
        approve(app_engine, w, pid, ctx=w["hq"])
        pids.append(pid)
        remaining -= amount
    extra = propose(app_engine, w, 1)
    approve(app_engine, w, extra)  # approvable now: nothing is reserved yet
    for pid in pids:
        assert execute_refund(app_engine, w["hq"], pid).status == "succeeded"
    with pytest.raises(ExecutionRefused, match="refundable balance"):
        execute_refund(app_engine, w["hq"], extra)
    assert sum(r.amount_paise for r in ledger(app_engine, w)) == w["total"]
    assert len(provider_ops(w)) == len(pids)


def test_approval_is_refused_when_the_balance_is_already_used(app_engine, world):
    w = world
    first = propose(app_engine, w, w["cap"])
    approve(app_engine, w, first)
    execute_refund(app_engine, w["hq"], first)
    if w["cap"] < w["total"]:
        pytest.skip("cap leaves balance; covered by test_over_refund_is_blocked")
    late = propose(app_engine, w, 1)
    with pytest.raises(NotEligible):
        approve(app_engine, w, late)


def test_expired_approval_is_blocked(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    decided = NOW - timedelta(days=2)
    approve(app_engine, w, pid, now=decided)
    with pytest.raises(ExecutionRefused, match="expired"):
        execute_refund(app_engine, w["hq"], pid, now=NOW)
    assert ledger(app_engine, w) == [] and provider_ops(w) == []


def test_changed_payload_is_blocked(app_engine, world):
    """A proposal whose stored params no longer hash to what was approved."""
    w = world
    pid, digest = uuid.uuid4(), "e" * 64
    amount = small(w)
    with tenant_session(w["tid"], app_engine) as s:
        s.add(
            ActionProposal(
                id=pid,
                tenant_id=w["tid"],
                case_id=w["case_id"],
                action="refund",
                params={
                    "transaction_id": str(w["order_id"]),
                    "amount_paise": amount,
                    "reason": "x",
                },
                payload_hash=digest,
                amount_paise=amount,
                amount_param="amount_paise",
                risk="high",
                reason="x",
            )
        )
        s.flush()
        s.add(
            Approval(
                tenant_id=w["tid"],
                proposal_id=pid,
                payload_hash=digest,
                decision="approved",
                mode="human",
                decided_by=w["hq"].user_id,
                decided_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )
        )
    with pytest.raises(ExecutionRefused, match="payload_changed"):
        execute_refund(app_engine, w["hq"], pid)
    assert provider_ops(w) == []


@pytest.mark.parametrize("decision", [None, "rejected"])
def test_unapproved_or_rejected_is_blocked(app_engine, world, decision):
    w = world
    pid = propose(app_engine, w, small(w))
    if decision:
        approve(app_engine, w, pid, decision=decision)
    with pytest.raises(ExecutionRefused, match="no_approval|rejected"):
        execute_refund(app_engine, w["hq"], pid)
    assert provider_ops(w) == []


# --- timeouts and reconciliation ------------------------------------------------------------


def test_accept_then_timeout_reconciles_without_duplicate(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    get_mock("payment").set_chaos(Chaos(accept_then_timeout_rate=1.0), merchant_id_for(w["tid"]))
    assert execute_refund(app_engine, w["hq"], pid).status == "unknown"  # never assumed
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(w["tid"]))
    assert reconcile_refund(app_engine, w["hq"], pid).status == "succeeded"
    assert len(provider_ops(w)) == 1
    assert [r.status for r in ledger(app_engine, w)] == ["succeeded"]


def test_timeout_before_accept_is_resent_with_the_same_key(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    get_mock("payment").set_chaos(Chaos(timeout_rate=1.0), merchant_id_for(w["tid"]))
    assert execute_refund(app_engine, w["hq"], pid).status == "unknown"
    assert provider_ops(w) == []  # nothing happened at the provider
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(w["tid"]))
    assert reconcile_refund(app_engine, w["hq"], pid).status == "succeeded"
    (op,) = provider_ops(w)
    assert op.idempotency_key == refund_key(pid)


def test_transient_errors_are_retried_with_the_same_key(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    get_mock("payment").set_chaos(Chaos(transient_error_rate=1.0), merchant_id_for(w["tid"]))
    assert execute_refund(app_engine, w["hq"], pid).status == "submitted"  # nothing applied
    assert [r.status for r in ledger(app_engine, w)] == ["reserved"]
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(w["tid"]))
    assert reconcile_refund(app_engine, w["hq"], pid).status == "succeeded"
    assert len(provider_ops(w)) == 1


# --- concurrency -----------------------------------------------------------------------------


def test_concurrent_workers_on_one_proposal_make_one_refund(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: execute_refund(app_engine, w["hq"], pid), range(6)))
    assert {r.status for r in results} == {"succeeded"}
    assert len(provider_ops(w)) == 1
    with tenant_session(w["tid"], app_engine) as s:
        assert (
            s.scalar(
                select(func.count()).select_from(Execution).where(Execution.proposal_id == pid)
            )
            == 1
        )


def test_concurrent_proposals_cannot_overdraw_an_order(app_engine, world):
    """Two approved refunds that each fit alone but not together, executed at once."""
    w = world
    amount = w["total"] // 2 + 1
    if amount > w["cap"]:
        pytest.skip("percent cap already prevents two refunds that each exceed half the order")
    a, b = propose(app_engine, w, amount), propose(app_engine, w, amount)
    approve(app_engine, w, a)
    approve(app_engine, w, b)

    def run(pid):
        try:
            return execute_refund(app_engine, w["hq"], pid).status
        except ExecutionRefused as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(run, [a, b]))
    assert outcomes[1] == "succeeded" and outcomes[0].startswith("not_eligible")
    assert len(provider_ops(w)) == 1


# --- who may approve ---------------------------------------------------------------------------


def _ctx_for(app_engine, w, email):
    with tenant_session(w["tid"], app_engine) as s:
        return load_context(s, w["tid"], s.scalar(select(User.id).where(User.email == email)))


def test_customers_and_out_of_scope_staff_cannot_approve(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    with tenant_session(w["tid"], app_engine) as s:
        location_id = s.get(Transaction, w["order_id"]).location_id
    for user in w["cfg"].users:
        ctx = _ctx_for(app_engine, w, user.email)
        if user.role == "customer" or (
            user.role != "hq_owner" and not ctx.can_see_location(location_id)
        ):
            with pytest.raises(NotFound):
                approve(app_engine, w, pid, ctx=ctx)


def test_in_scope_manager_can_approve_and_a_second_decision_fails(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    with tenant_session(w["tid"], app_engine) as s:
        location_id = s.get(Transaction, w["order_id"]).location_id
    managers = [u for u in w["cfg"].users if u.role == "location_manager"]
    manager = next(
        (m for m in managers if _ctx_for(app_engine, w, m.email).can_see_location(location_id)),
        None,
    )
    if manager is None:
        pytest.skip("no manager scoped to this order's location")
    approve(app_engine, w, pid, ctx=_ctx_for(app_engine, w, manager.email))
    with pytest.raises(AlreadyDecided):
        approve(app_engine, w, pid)  # a second manager / double submit


def test_refunds_are_never_auto_approved(app_engine, world):
    w = world
    pid = propose(app_engine, w, 1)
    with tenant_session(w["tid"], app_engine) as s:
        assert auto_decide(s, w["tid"], pid, NOW) is None


# --- review follow-ups: stale results, resume after expiry, blind resend, error parity ------


def test_a_stale_outcome_never_downgrades_a_finished_refund(app_engine, world):
    from app.connectors.base import RefundOutcome
    from app.engine.executor import _persist

    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    done = execute_refund(app_engine, w["hq"], pid)
    late = _persist(app_engine, w["hq"], pid, done.idempotency_key, RefundOutcome("processing"))
    assert late.status == "succeeded" and late.provider_reference == done.provider_reference
    assert [r.status for r in ledger(app_engine, w)] == ["succeeded"]
    with tenant_session(w["tid"], app_engine) as s:
        assert (
            s.scalar(
                select(func.count()).select_from(DomainEvent).where(DomainEvent.entity_id == pid)
            )
            == 1
        )


def test_resume_after_expiry_quarantines_instead_of_freeing_money(app_engine, world):
    """'No record yet' isn't proof nothing will land: keep the balance held, send nothing."""
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid, now=NOW - timedelta(hours=1))
    get_mock("payment").set_chaos(Chaos(timeout_rate=1.0), merchant_id_for(w["tid"]))
    assert execute_refund(app_engine, w["hq"], pid).status == "unknown"
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(w["tid"]))
    later = NOW + timedelta(days=3)  # approval long expired, provider has no record
    with pytest.raises(ExecutionRefused, match="expired"):
        execute_refund(app_engine, w["hq"], pid, now=later)
    assert provider_ops(w) == []
    assert [r.status for r in ledger(app_engine, w)] == ["pending_reconciliation"]
    with tenant_session(w["tid"], app_engine) as s:
        _, facts = order_facts(s, w["order_id"])
    assert facts.refundable_paise == w["total"] - small(w)  # still held: no double refund


def test_a_late_landing_after_quarantine_is_recorded_once(app_engine, world):
    """The in-flight request lands after we quarantined: record it, never refund twice."""
    from mocks.payment import RefundRequest

    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid, now=NOW - timedelta(hours=1))
    get_mock("payment").set_chaos(Chaos(timeout_rate=1.0), merchant_id_for(w["tid"]))
    execute_refund(app_engine, w["hq"], pid)
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(w["tid"]))
    with pytest.raises(ExecutionRefused):
        execute_refund(app_engine, w["hq"], pid, now=NOW + timedelta(days=3))
    with tenant_session(w["tid"], app_engine) as s:  # the original request finally lands
        payment_ref = s.scalar(
            select(Payment.provider_reference).where(Payment.transaction_id == w["order_id"])
        )
    get_mock("payment").refund(
        merchant_id_for(w["tid"]),
        refund_key(pid),
        RefundRequest(payment_reference=payment_ref, amount_paise=small(w)),
    )
    assert reconcile_refund(app_engine, w["hq"], pid).status == "succeeded"
    assert [r.status for r in ledger(app_engine, w)] == ["succeeded"]
    assert len(provider_ops(w)) == 1


def test_stale_non_terminal_answers_never_move_backwards(app_engine, world):
    from app.connectors.base import RefundOutcome
    from app.engine.executor import _persist

    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    get_mock("payment").set_chaos(
        Chaos(processing_rate=1.0, settle_after_polls=50), merchant_id_for(w["tid"])
    )
    assert execute_refund(app_engine, w["hq"], pid).status == "processing"
    stale = _persist(app_engine, w["hq"], pid, refund_key(pid), RefundOutcome("unknown"))
    assert stale.status == "processing"


def test_resume_after_expiry_still_records_money_already_sent(app_engine, world):
    """Expiry gates sending, not recording: if the provider has it, we record it."""
    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    get_mock("payment").set_chaos(Chaos(accept_then_timeout_rate=1.0), merchant_id_for(w["tid"]))
    assert execute_refund(app_engine, w["hq"], pid).status == "unknown"
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(w["tid"]))
    later = NOW + timedelta(days=3)
    assert execute_refund(app_engine, w["hq"], pid, now=later).status == "succeeded"
    assert len(provider_ops(w)) == 1


def test_resume_does_not_resend_when_the_lookup_is_unavailable(app_engine, world, monkeypatch):
    from app.connectors.base import RefundOutcome
    from app.connectors.mock_connectors import MockPaymentConnector

    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    get_mock("payment").set_chaos(Chaos(timeout_rate=1.0), merchant_id_for(w["tid"]))
    assert execute_refund(app_engine, w["hq"], pid).status == "unknown"
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(w["tid"]))
    monkeypatch.setattr(
        MockPaymentConnector, "find_refund", lambda self, ctx, key: RefundOutcome("unavailable")
    )
    assert execute_refund(app_engine, w["hq"], pid).status == "unknown"  # unchanged
    assert provider_ops(w) == []  # no blind resend


def test_out_of_scope_and_missing_proposals_look_the_same(app_engine, world):
    w = world
    pid = propose(app_engine, w, small(w))
    with tenant_session(w["tid"], app_engine) as s:
        location_id = s.get(Transaction, w["order_id"]).location_id
    outsider = next(
        (
            u
            for u in w["cfg"].users
            if u.role in ("location_manager", "franchisee_owner")
            and not _ctx_for(app_engine, w, u.email).can_see_location(location_id)
        ),
        None,
    )
    if outsider is None:
        pytest.skip("every scoped user in this tenant can see this order's location")
    ctx = _ctx_for(app_engine, w, outsider.email)
    errors = []
    for target in (pid, uuid.uuid4()):
        with pytest.raises(NotFound) as exc:
            approve(app_engine, w, target, ctx=ctx)
        errors.append((type(exc.value), str(exc.value)))
    assert errors[0] == errors[1]
