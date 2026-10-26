"""Chaos suite (E4.3, PROJECT.md section 15), for every tenant.

50 customer reports per tenant go through the real API (in-process TestClient, real DB) while
the payment provider times out (p=0.3), is unavailable, accepts and then times out, settles
late, and lets requests land after we gave up on them. On top of that: double submits of the
same report and of the same decision, two staff deciding one proposal at once, workers killed
between the decision commit and execution and in the middle of execution, and concurrent
reconciles. At the end, per tenant:

- zero duplicate provider refunds (one provider operation per proposal key, none unapproved)
- refunded per order never exceeds what was paid (provider truth and ledger holdings)
- ledger and execution statuses only ever moved forward
- every approved refund ends succeeded / failed / pending_reconciliation (never silently lost)
- a customer never saw "confirmed" without provider success
- no cross-tenant visibility of any of it
"""

import math
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.api import routes_approvals
from app.connectors.mock_connectors import MockPaymentConnector
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Customer,
    DomainEvent,
    Execution,
    LineItem,
    Payment,
    RefundOperation,
    Ticket,
    Transaction,
    User,
)
from app.core.money import percent_of
from app.core.tenancy import load_context, tenant_id_for
from app.core.verticals import load_pack
from app.engine.cases import OPEN_STATUSES
from app.engine.eligibility import CAPTURED_STATUSES, HOLDING_STATUSES, order_facts
from app.engine.executor import ExecutionRefused, execute_refund, refund_key
from app.engine.proposals import create_proposal
from app.engine.sweeper import sweep_tenant
from mocks.base import Chaos
from mocks.payment import RefundRequest
from mocks.registry import get_mock, merchant_id_for, reset_mocks
from tests.helpers import login

pytestmark = pytest.mark.chaos

CASES = 50
WORKERS = 8
CHAOS = Chaos(
    timeout_rate=0.3,
    transient_error_rate=0.15,
    accept_then_timeout_rate=0.1,
    processing_rate=0.15,
    settle_after_polls=2,
    seed=4242,
)
# Forward order of each status column. Equal rank = both final.
LEDGER_RANK = {
    "reserved": 0,
    "submitted": 1,
    "unknown": 2,
    "pending_reconciliation": 3,
    "succeeded": 4,
    "failed": 4,
}
EXEC_RANK = {"submitted": 0, "unknown": 1, "processing": 2, "succeeded": 3, "failed": 3}
FINAL_LEDGER = ("succeeded", "failed", "pending_reconciliation")


class WorkerKilled(Exception):
    """The process running the refund died here."""


@dataclass
class Order:
    id: uuid.UUID
    location_id: uuid.UUID
    owner_email: str
    refundable_paise: int
    cap_paise: int
    line_id: uuid.UUID
    original_fulfilled: int
    original_customer: uuid.UUID
    case_id: uuid.UUID | None = None
    proposal_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class World:
    cfg: object
    tid: uuid.UUID
    merchant: str
    category: str
    orders: list[Order]
    headers: dict[str, dict]  # email -> auth header
    hq_email: str
    staff_ctx: dict  # email -> TenantContext
    other: dict  # another tenant: {"hq": header, "customer": header, "merchant": str}


def _pool():
    return ThreadPoolExecutor(max_workers=WORKERS)


@pytest.fixture
def world(request, api, app_engine, maint_engine, seeded_history, tenant):
    reset_mocks()
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    pack = load_pack(cfg.vertical_pack)
    category = next(c for c, rule in pack.remedies.items() if rule == "refund_missing")
    customers = [u.email for u in cfg.users if u.role == "customer"]
    staff = [u.email for u in cfg.users if u.role != "customer"]
    hq_email = next(u.email for u in cfg.users if u.role == "hq_owner")
    others = [name for name in seeded_history if name != tenant.name]
    if not others:
        pytest.skip("cross-tenant checks need a second seeded tenant")
    orders: list[Order] = []  # filled as rows are changed; the finalizer restores them
    lent: list[Order] = []
    started = datetime.now(UTC)
    request.addfinalizer(lambda: _cleanup(app_engine, maint_engine, tid, orders, lent, started))
    with tenant_session(tid, app_engine) as s:
        owner_of = {}
        for email in customers:
            uid = s.scalar(select(User.id).where(User.email == email))
            owner_of[s.scalar(select(Customer.id).where(Customer.user_id == uid))] = email
        staff_ctx = {
            e: load_context(s, tid, s.scalar(select(User.id).where(User.email == e))) for e in staff
        }
        # Orders with no open case (a report would join it) and money left to refund.
        has_open_case = (
            select(Case.id)
            .where(Case.transaction_id == Transaction.id, Case.status.in_(OPEN_STATUSES))
            .exists()
        )
        # The demo customers' own orders first; a small seeded history may not have enough,
        # so other customers' orders are lent to them for the run (restored afterwards).
        candidates = s.scalars(
            select(Transaction)
            .where(~has_open_case)
            .order_by(
                Transaction.customer_id.in_(owner_of).desc(),
                Transaction.placed_at.desc(),
                Transaction.id,
            )
            .limit(CASES * 3)
        ).all()
        demo_ids = list(owner_of)
        for t in candidates:
            line = s.scalars(
                select(LineItem)
                .where(LineItem.transaction_id == t.id)
                .order_by(LineItem.unit_price_paise.desc(), LineItem.id)
                .limit(1)
            ).one()
            _, facts = order_facts(s, t.id)
            if facts.refundable_paise <= 0:
                continue
            orders.append(
                Order(
                    id=t.id,
                    location_id=t.location_id,
                    owner_email=owner_of.get(t.customer_id)
                    or owner_of[demo_ids[len(orders) % len(demo_ids)]],
                    refundable_paise=facts.refundable_paise,
                    cap_paise=percent_of(t.total_paise, facts.settings["refund_max_percent"]),
                    line_id=line.id,
                    original_fulfilled=line.quantity_fulfilled,
                    original_customer=t.customer_id,
                )
            )
            # One unit of the priciest line missing: the pack's refund_missing remedy applies.
            s.execute(
                update(LineItem)
                .where(LineItem.id == line.id)
                .values(quantity_fulfilled=line.quantity - 1)
            )
            if len(orders) == CASES:
                break
    assert len(orders) == CASES, "seeded history has too few orders"
    owner_id = {email: cid for cid, email in owner_of.items()}
    lent.extend(o for o in orders if o.original_customer not in owner_of)
    with tenant_session(tid, maint_engine) as s:
        for o in lent:
            s.execute(
                update(Transaction)
                .where(Transaction.id == o.id)
                .values(customer_id=owner_id[o.owner_email])
            )
    headers = {e: login(api, cfg.slug, e) for e in customers + staff}
    other_cfg = seeded_history[others[0]]
    other = {
        "hq": login(
            api, other_cfg.slug, next(u.email for u in other_cfg.users if u.role == "hq_owner")
        ),
        "customer": login(
            api, other_cfg.slug, next(u.email for u in other_cfg.users if u.role == "customer")
        ),
        "merchant": merchant_id_for(tenant_id_for(other_cfg.slug)),
    }
    w = World(cfg, tid, merchant_id_for(tid), category, orders, headers, hq_email, staff_ctx, other)
    yield w


def _cleanup(app_engine, maint_engine, tid, orders, lent, started):
    """Undo everything the run changed or created, even if setup failed half way."""
    reset_mocks()
    order_ids = [o.id for o in orders]
    with tenant_session(tid, app_engine) as s:
        for o in orders:
            s.execute(
                update(LineItem)
                .where(LineItem.id == o.line_id)
                .values(quantity_fulfilled=o.original_fulfilled)
            )
    with tenant_session(tid, maint_engine) as s:
        case_ids = s.scalars(
            select(Case.id).where(
                Case.tenant_id == tid,
                Case.transaction_id.in_(order_ids),
                Case.opened_at >= started,
            )
        ).all()
        proposal_ids = s.scalars(
            select(ActionProposal.id).where(
                ActionProposal.tenant_id == tid, ActionProposal.case_id.in_(case_ids)
            )
        ).all()
        entity_ids = [*case_ids, *proposal_ids]
        for model in (AuditEvent, DomainEvent):
            s.execute(delete(model).where(model.tenant_id == tid, model.entity_id.in_(entity_ids)))
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(case_ids)))
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid, RefundOperation.proposal_id.in_(proposal_ids)
            )
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id.in_(case_ids)))
        for o in lent:
            s.execute(
                update(Transaction)
                .where(Transaction.id == o.id)
                .values(customer_id=o.original_customer)
            )


class Observer:
    """Snapshots of every ledger/execution status and every customer-visible stage."""

    def __init__(self, api, app_engine, w: World):
        self.api, self.engine, self.w = api, app_engine, w
        self.ledger_seen: dict[uuid.UUID, list[str]] = defaultdict(list)
        self.exec_seen: dict[uuid.UUID, list[str]] = defaultdict(list)
        self.confirmed_without_success: list[tuple] = []
        self.polls = 0

    def all_pids(self):
        return [p for o in self.w.orders for p in o.proposal_ids]

    def snapshot(self):
        pids = self.all_pids()
        with tenant_session(self.w.tid, self.engine) as s:
            for pid, st in s.execute(
                select(RefundOperation.proposal_id, RefundOperation.status).where(
                    RefundOperation.proposal_id.in_(pids)
                )
            ):
                self.ledger_seen[pid].append(st)
            for pid, st in s.execute(
                select(Execution.proposal_id, Execution.status).where(
                    Execution.proposal_id.in_(pids)
                )
            ):
                self.exec_seen[pid].append(st)

    def poll_customers(self):
        """What each customer is told right now. Confirmed needs provider success."""
        ops = {op.idempotency_key: op for op in get_mock("payment").operations(self.w.merchant)}

        def one(o: Order):
            r = self.api.get(f"/cases/{o.case_id}", headers=self.w.headers[o.owner_email])
            assert r.status_code == 200, r.text
            return o, r.json()

        with _pool() as pool:
            for o, body in pool.map(one, self.w.orders):
                self.polls += 1
                if body["stage"] == "confirmed":
                    op = ops.get(refund_key(uuid.UUID(body["proposal_id"])))
                    if op is None or op.status != "succeeded":
                        self.confirmed_without_success.append((o.case_id, body))

    def checkpoint(self):
        self.snapshot()
        self.poll_customers()


def _post(api, path, headers, json=None):
    return api.post(path, headers=headers, json=json)


def _decide(api, w, email, pid, decision="approved"):
    return _post(
        api, f"/approvals/{pid}/decision", w.headers[email], {"decision": decision}
    ).status_code


def _run_executor(app_engine, w, pid):
    try:
        return execute_refund(app_engine, _hq_ctx(w), pid).status
    except ExecutionRefused as exc:
        return exc.reason
    except WorkerKilled:
        return "killed"


def _hq_ctx(w):
    return w.staff_ctx[w.hq_email]


def _second_decider(w, order: Order) -> str:
    """Another staff member who can decide this order (falls back to the hq owner twice)."""
    for email, ctx in w.staff_ctx.items():
        if email != w.hq_email and ctx.can_see_location(order.location_id):
            return email
    return w.hq_email


def test_chaos_run_keeps_money_safe(api, app_engine, world, monkeypatch):
    w = world
    payment = get_mock("payment")
    payment.set_chaos(CHAOS, w.merchant)
    obs = Observer(api, app_engine, w)

    # --- 1. every report submitted twice at once: one case, one proposal per order --------
    def report(o: Order):
        r = _post(
            api,
            "/cases",
            w.headers[o.owner_email],
            {
                "transaction_id": str(o.id),
                "category": w.category,
                "message": "An item was missing from my order.",
            },
        )
        assert r.status_code == 201, r.text
        return o, r.json()

    with _pool() as pool:
        opened = list(pool.map(report, [o for o in w.orders for _ in range(2)]))
    by_order = defaultdict(list)
    for o, body in opened:
        by_order[o.id].append(body)
    for o in w.orders:
        first, second = by_order[o.id]
        assert first["id"] == second["id"], "a double submit opened two cases"
        o.case_id = uuid.UUID(first["id"])
    with tenant_session(w.tid, app_engine) as s:
        for o in w.orders:
            props = s.scalars(
                select(ActionProposal.id).where(ActionProposal.case_id == o.case_id)
            ).all()
            assert len(props) == 1, "a double submit created two proposals"
            o.proposal_ids = list(props)
    assert all(b["stage"] == "awaiting_approval" for _, b in opened)

    groups = {
        "double_decision": w.orders[0:8],
        "two_staff": w.orders[8:16],
        "kill_after_commit": w.orders[16:24],
        "kill_before_send": w.orders[24:28],
        "kill_after_send": w.orders[28:32],
        "rejected": w.orders[32:35],
        "normal": w.orders[35:],
    }
    pressure = groups["kill_after_commit"][:3]

    # --- 2. over-refund pressure: more approved refunds on one order than was paid --------
    with tenant_session(w.tid, app_engine) as s:
        for o in pressure:
            first_amount = s.get(ActionProposal, o.proposal_ids[0]).amount_paise
            each = min(o.cap_paise, o.refundable_paise)
            extras = math.ceil((o.refundable_paise - first_amount + 1) / each)
            for _ in range(extras):
                p = create_proposal(
                    s,
                    w.tid,
                    case_id=o.case_id,
                    action="refund",
                    reason="chaos: over-refund pressure",
                    params={"transaction_id": str(o.id), "amount_paise": each, "reason": "x"},
                )
                o.proposal_ids.append(p.id)
    obs.checkpoint()

    # --- 3a. decisions with the background refund running (under provider chaos) ----------
    jobs = []
    for o in groups["double_decision"]:  # same approver, same decision, twice at once
        jobs += [(w.hq_email, o.proposal_ids[0], "approved")] * 2
    for o in groups["two_staff"]:  # two staff, opposite decisions, at once
        jobs += [
            (w.hq_email, o.proposal_ids[0], "approved"),
            (_second_decider(w, o), o.proposal_ids[0], "rejected"),
        ]
    for o in groups["rejected"]:
        jobs.append((w.hq_email, o.proposal_ids[0], "rejected"))
    for o in groups["normal"]:
        jobs.append((w.hq_email, o.proposal_ids[0], "approved"))
    with _pool() as pool:
        codes = list(pool.map(lambda j: (j[1], _decide(api, w, *j[:2], j[2])), jobs))
    per_pid = defaultdict(list)
    for pid, code in codes:
        per_pid[pid].append(code)
    for o in groups["double_decision"] + groups["two_staff"]:
        got = sorted(per_pid[o.proposal_ids[0]])
        assert got[0] == 200 and all(c in (403, 409) for c in got[1:]), got
    assert all(per_pid[o.proposal_ids[0]] == [200] for o in groups["rejected"] + groups["normal"])

    # --- 3b. worker killed between the decision commit and execution --------------------
    with monkeypatch.context() as m:
        m.setattr(routes_approvals, "run_execution", lambda *a, **k: None)
        kill_jobs = [
            (w.hq_email, pid, "approved")
            for o in groups["kill_after_commit"]
            + groups["kill_before_send"]
            + groups["kill_after_send"]
            for pid in o.proposal_ids
        ]
        with _pool() as pool:
            assert set(pool.map(lambda j: _decide(api, w, *j[:2], j[2]), kill_jobs)) == {200}
    obs.checkpoint()

    # --- 3c. worker killed mid-execution: after reserving, before / after the provider call
    real_refund = MockPaymentConnector.refund

    def die_before(self, *a, **k):
        raise WorkerKilled

    def die_after(self, *a, **k):
        real_refund(self, *a, **k)
        raise WorkerKilled

    for killer, members in ((die_before, "kill_before_send"), (die_after, "kill_after_send")):
        with monkeypatch.context() as m:
            m.setattr(MockPaymentConnector, "refund", killer)
            pids = [o.proposal_ids[0] for o in groups[members]]
            with _pool() as pool:
                list(pool.map(lambda pid: _run_executor(app_engine, w, pid), pids))
    obs.checkpoint()

    # --- 4. restarted workers pick up the approved-but-never-run refunds, twice at once ----
    restart = [pid for o in groups["kill_after_commit"] for pid in o.proposal_ids] * 2
    with _pool() as pool:
        restart_results = list(pool.map(lambda pid: _run_executor(app_engine, w, pid), restart))
    assert any(r.startswith("not_eligible") for r in restart_results), (
        "over-refund pressure never hit the balance check"
    )
    obs.checkpoint()

    # --- 5. late landings: requests we never heard back about arrive at the provider ------
    with tenant_session(w.tid, app_engine) as s:
        silent = s.execute(
            select(Execution.proposal_id, RefundOperation.amount_paise, Payment.provider_reference)
            .join(RefundOperation, RefundOperation.proposal_id == Execution.proposal_id)
            .join(Payment, Payment.transaction_id == RefundOperation.transaction_id)
            .where(
                Execution.proposal_id.in_(obs.all_pids()),
                Execution.status.in_(("unknown", "submitted")),
                Payment.status.in_(CAPTURED_STATUSES),
            )
        ).all()
    landed = 0
    for i, (pid, amount, payment_ref) in enumerate(silent):
        if i % 2 or payment.get_refund(w.merchant, refund_key(pid)) is not None:
            continue
        payment.set_chaos(Chaos(), w.merchant)
        payment.refund(
            w.merchant,
            refund_key(pid),
            RefundRequest(payment_reference=payment_ref, amount_paise=amount),
        )
        payment.set_chaos(CHAOS, w.merchant)
        landed += 1
    obs.checkpoint()

    # --- 6. reconcile: concurrent duplicate reconciles, chaos on, then the provider heals --
    def unfinished():
        with tenant_session(w.tid, app_engine) as s:
            return s.scalars(
                select(Execution.proposal_id).where(
                    Execution.proposal_id.in_(obs.all_pids()),
                    Execution.status.notin_(("succeeded", "failed")),
                )
            ).all()

    def reconcile(pid):
        return _post(api, f"/approvals/{pid}/reconcile", w.headers[w.hq_email]).status_code

    for round_ in range(8):
        if round_ == 3:
            payment.set_chaos(Chaos(), w.merchant)
        todo = unfinished()
        if not todo:
            break
        with _pool() as pool:
            assert set(pool.map(reconcile, todo * 2)) == {202}
        obs.checkpoint()
    obs.checkpoint()

    # --- 7. the sweeper verifies refunds the provider answered for but whose worker died ---
    # before the verify step (phases 3c/4 call the executor alone): "confirmed" needs a verdict.
    sweep_tenant(app_engine, w.tid, min_age=timedelta(0))
    obs.checkpoint()

    _assert_invariants(api, app_engine, w, obs, groups)


def _assert_invariants(api, app_engine, w: World, obs: Observer, groups):
    pids = obs.all_pids()
    ops = get_mock("payment").operations(w.merchant)
    with tenant_session(w.tid, app_engine) as s:
        proposals = {
            p.id: p for p in s.scalars(select(ActionProposal).where(ActionProposal.id.in_(pids)))
        }
        approvals = {
            a.proposal_id: a
            for a in s.scalars(select(Approval).where(Approval.proposal_id.in_(pids)))
        }
        approval_rows = s.scalar(
            select(func.count()).select_from(Approval).where(Approval.proposal_id.in_(pids))
        )
        executions = {
            e.proposal_id: e
            for e in s.scalars(select(Execution).where(Execution.proposal_id.in_(pids)))
        }
        ledger = {
            r.proposal_id: r
            for r in s.scalars(select(RefundOperation).where(RefundOperation.proposal_id.in_(pids)))
        }
        s.expunge_all()  # keep the loaded values readable after the commit
    approved = {pid for pid, a in approvals.items() if a.decision == "approved"}

    # The chaos actually bit: timeouts left refunds unknown, and some of those were later
    # found or re-sent (same key) and completed at the provider.
    timed_out = {pid for pid, history in obs.exec_seen.items() if "unknown" in history}
    assert timed_out
    assert any(op.idempotency_key in {refund_key(p) for p in timed_out} for op in ops)

    # One decision per proposal, whatever raced.
    assert approval_rows == len(approvals)

    # Zero duplicate provider refunds: one operation per key, only for approved proposals.
    keys = [op.idempotency_key for op in ops]
    assert len(keys) == len(set(keys))
    key_to_pid = {refund_key(pid): pid for pid in pids}
    assert set(keys) <= {refund_key(pid) for pid in approved}, "provider refund without approval"
    for op in ops:
        assert op.request.amount_paise == proposals[key_to_pid[op.idempotency_key]].amount_paise

    # Never refunded more than was paid, per order (provider truth and ledger holdings).
    for o in w.orders:
        order_keys = {refund_key(pid) for pid in o.proposal_ids}
        moved = sum(
            op.request.amount_paise
            for op in ops
            if op.idempotency_key in order_keys and op.status in ("succeeded", "processing")
        )
        held = sum(
            ledger[pid].amount_paise
            for pid in o.proposal_ids
            if pid in ledger and ledger[pid].status in HOLDING_STATUSES
        )
        assert moved <= o.refundable_paise and held <= o.refundable_paise, o.id

    # Ledger and execution only moved forward.
    for seen, rank in ((obs.ledger_seen, LEDGER_RANK), (obs.exec_seen, EXEC_RANK)):
        for pid, history in seen.items():
            ranks = [rank[st] for st in history]
            assert ranks == sorted(ranks), (pid, history)
            finals = {st for st in history if rank[st] == max(rank.values())}
            assert len(finals) <= 1, (pid, history)  # a final state never flips

    # Every approved refund ends in a final, recorded state: never silently lost.
    for pid in approved:
        execution = executions.get(pid)
        assert execution is not None, f"approved refund {pid} has no execution record"
        row = ledger.get(pid)
        assert execution.status in ("succeeded", "failed") or (
            row is not None and row.status == "pending_reconciliation"
        ), (pid, execution.status, row and row.status)
        if row is not None:
            assert row.status in FINAL_LEDGER, (pid, row.status)

    # Our records agree with the provider's.
    op_by_key = {op.idempotency_key: op for op in ops}
    for pid, row in ledger.items():
        op = op_by_key.get(row.idempotency_key)
        if row.status == "succeeded":
            assert op is not None and op.status == "succeeded", pid
        if op is not None and op.status == "succeeded":
            assert row.status == "succeeded", pid
    for pid, execution in executions.items():
        op = op_by_key.get(execution.idempotency_key)
        succeeded = op is not None and op.status == "succeeded"
        assert (execution.status == "succeeded") == succeeded, pid

    # The customer never saw "confirmed" without provider success, and does now iff it is.
    assert obs.confirmed_without_success == []
    for o in w.orders:
        body = api.get(f"/cases/{o.case_id}", headers=w.headers[o.owner_email]).json()
        op = op_by_key.get(refund_key(uuid.UUID(body["proposal_id"])))
        assert (body["stage"] == "confirmed") == (op is not None and op.status == "succeeded")
    for o in groups["rejected"]:
        assert (
            api.get(f"/cases/{o.case_id}", headers=w.headers[o.owner_email]).json()["stage"]
            == "declined"
        )

    # No cross-tenant visibility.
    our_cases = {str(o.case_id) for o in w.orders}
    for who in ("hq", "customer"):
        listed = api.get("/cases?limit=200", headers=w.other[who]).json()
        assert our_cases.isdisjoint(c["id"] for c in listed)
    queue = api.get("/approvals?limit=500", headers=w.other["hq"]).json()
    assert {str(p) for p in pids}.isdisjoint(p["proposal_id"] for p in queue)
    for o in w.orders[:: max(1, len(w.orders) // 10)]:
        assert api.get(f"/cases/{o.case_id}", headers=w.other["customer"]).status_code == 404
        assert api.get(f"/cases/{o.case_id}", headers=w.other["hq"]).status_code == 404
        pid = o.proposal_ids[0]
        assert _post(api, f"/approvals/{pid}/reconcile", w.other["hq"]).status_code == 404
        assert (
            _post(
                api, f"/approvals/{pid}/decision", w.other["hq"], {"decision": "approved"}
            ).status_code
            == 404
        )
    other_keys = {op.idempotency_key for op in get_mock("payment").operations(w.other["merchant"])}
    assert other_keys.isdisjoint(keys)
