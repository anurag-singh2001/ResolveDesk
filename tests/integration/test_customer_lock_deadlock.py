"""S6.2: deterministic reproduction of the S5.2 customer-lock deadlock, and proof of the fix
(DECISIONS.md "Customer lock: exclusive, and case before customer").

Two things deadlocked before commit 0c410a7:
1. open_case took the customer row FOR SHARE (cases.lock_customer) and approvals.auto_decide
   later takes the same row FOR UPDATE in the same transaction. Two concurrent cases of one
   customer each held a share lock and each waited to upgrade: Postgres aborts one.
2. add_reply locked customer then case, while the graph locks case then customer.

The tests drive the real code and make the race deterministic with hooks: a barrier placed
just before auto_decide holds both transactions after their first lock. With the exclusive
lock the second transaction is blocked at the customer lock, so the barrier times out (short,
swallowed) and the two run one after the other. Each "regression guard" test puts the old
behaviour back and EXPECTS the deadlock, which proves the test can see it.
Every tenant runs; none is named. All waits are bounded (lock_timeout, barrier timeouts).
"""

import contextlib
import threading
from datetime import UTC, datetime

import psycopg.errors
import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.core.models import Case, Customer, Ticket, Transaction, User
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import load_context, tenant_id_for
from app.engine import cases, lifecycle
from app.engine.cases import open_case

BARRIER_WAIT = 2.0  # seconds a transaction waits for its peer to hold the first lock
LOCK_TIMEOUT = "10s"  # a failure must not hang the suite


@pytest.fixture
def pair(app_engine, maint_engine, seeded_history, tenant):
    """One customer with two orders that have no case yet, and the voucher category whose
    remedy reaches auto_decide."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        voucher_categories = [c for c, r in tenant_pack(s).remedies.items() if r == "voucher"]
        if not voucher_categories:
            pytest.skip("this vertical has no voucher remedy to auto-approve")
        has_case = select(Case.transaction_id).where(Case.transaction_id.is_not(None))
        rows = s.execute(
            select(Transaction.customer_id, Transaction.id)
            .join(Customer, Customer.id == Transaction.customer_id)
            .where(Transaction.id.not_in(has_case), Customer.user_id.is_not(None))
            .order_by(Transaction.customer_id, Transaction.placed_at.desc())
        ).all()
        by_customer: dict = {}
        for customer_id, order_id in rows:
            by_customer.setdefault(customer_id, []).append(order_id)
        found = next(((c, o[:2]) for c, o in by_customer.items() if len(o) >= 2), None)
        if found is None:
            pytest.skip("no customer with two orders that have no case")
        customer_id, orders = found
        user_id = s.get(Customer, customer_id).user_id
        ctx = load_context(s, tid, user_id)
    assert ctx is not None and ctx.role == "customer"
    yield {"tid": tid, "ctx": ctx, "orders": orders, "category": voucher_categories[0]}
    with tenant_session(tid, maint_engine) as s:
        mine = select(Case.id).where(Case.tenant_id == tid, Case.transaction_id.in_(orders))
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(mine)))
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.transaction_id.in_(orders)))


def _bounded(session):
    session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def _run_pair(jobs):
    """Run two callables in threads; return [None | exception] in order."""
    out: list = [None, None]

    def wrap(i, fn):
        try:
            fn()
        except BaseException as e:  # noqa: BLE001 - the test inspects it
            out[i] = e

    threads = [threading.Thread(target=wrap, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
        assert not t.is_alive(), "a transaction hung"
    return out


def _is_deadlock(err) -> bool:
    return isinstance(err, DBAPIError) and isinstance(err.orig, psycopg.errors.DeadlockDetected)


def _lock_customer_shared(session, where, user_id):
    """The OLD lock_customer: FOR SHARE."""
    customer = session.scalar(select(Customer).where(where).with_for_update(read=True))
    erased = session.scalar(select(User.erased_at).where(User.id == user_id))
    if customer is None or erased is not None:
        raise cases.CaseNotFound("account not found")
    return customer


def _open_two(pair, app_engine, monkeypatch):
    """Two concurrent open_case calls of one customer, held at the point just before
    auto_decide. Returns (errors, number that reached auto_decide)."""
    barrier = threading.Barrier(2)
    reached = []
    real = lifecycle.auto_decide

    def hooked(session, tenant_id, proposal_id, now):
        reached.append(1)
        # A broken barrier means the peer is blocked behind our lock (the fixed behaviour).
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(BARRIER_WAIT)
        return real(session, tenant_id, proposal_id, now)

    monkeypatch.setattr(lifecycle, "auto_decide", hooked)

    def report(order_id):
        def go():
            with tenant_session(pair["tid"], app_engine) as s:
                _bounded(s)
                open_case(
                    s,
                    pair["ctx"],
                    transaction_id=order_id,
                    category=pair["category"],
                    message="Wrong item.",
                    now=datetime.now(UTC),
                )

        return go

    errors = _run_pair([report(o) for o in pair["orders"]])
    return errors, len(reached)


def test_two_cases_of_one_customer_reaching_auto_decide_do_not_deadlock(
    pair, app_engine, monkeypatch
):
    errors, reached = _open_two(pair, app_engine, monkeypatch)
    assert errors == [None, None], errors
    if reached < 2:
        pytest.skip("the voucher remedy did not reach auto_decide for this tenant")
    with tenant_session(pair["tid"], app_engine) as s:
        opened = s.scalar(
            select(func.count()).select_from(Case).where(Case.transaction_id.in_(pair["orders"]))
        )
    assert opened == 2


def test_regression_guard_the_old_share_lock_deadlocks(pair, app_engine, monkeypatch):
    """Regression guard: the old lock mode (FOR SHARE, then auto_decide's FOR UPDATE)
    deadlocks. If this stops failing the way it should, the test above proves nothing."""
    monkeypatch.setattr(cases, "lock_customer", _lock_customer_shared)
    errors, reached = _open_two(pair, app_engine, monkeypatch)
    if reached < 2:
        pytest.skip("the voucher remedy did not reach auto_decide for this tenant")
    assert sum(_is_deadlock(e) for e in errors) == 1, errors  # Postgres aborts one victim
    assert sum(e is None for e in errors) == 1  # the other one commits


@pytest.fixture
def waiting_case(pair, app_engine):
    """A free-text case of the customer, paused awaiting info (what add_reply answers)."""
    with tenant_session(pair["tid"], app_engine) as s:
        case, _ = open_case(
            s,
            pair["ctx"],
            transaction_id=pair["orders"][0],
            category=None,
            message="Something is wrong.",
            now=datetime.now(UTC),
        )
        s.execute(update(Case).where(Case.id == case.id).values(status="awaiting_info"))
        return {"case_id": case.id, "customer_id": case.customer_id}


def _graph_order_then_peer(pair, app_engine, waiting_case, peer):
    """The graph's lock order (case, then customer) against `peer`. Returns the errors."""
    case_held = threading.Event()
    customer_held = threading.Event()

    def graph():
        with tenant_session(pair["tid"], app_engine) as s:
            _bounded(s)
            s.scalar(select(Case).where(Case.id == waiting_case["case_id"]).with_for_update())
            case_held.set()
            customer_held.wait(BARRIER_WAIT)  # let the peer take its first lock
            s.scalar(
                select(Customer).where(Customer.id == waiting_case["customer_id"]).with_for_update()
            )

    def reply():
        assert case_held.wait(10)
        with tenant_session(pair["tid"], app_engine) as s:
            _bounded(s)
            peer(s, customer_held)

    return _run_pair([graph, reply])


def test_add_reply_and_the_graph_lock_in_the_same_order(pair, app_engine, waiting_case):
    """The real add_reply against a transaction locking in the graph's order."""
    case = type(
        "C", (), {"id": waiting_case["case_id"], "customer_id": waiting_case["customer_id"]}
    )

    def peer(session, customer_held):
        cases.add_reply(session, pair["ctx"], case, "the costliest item", datetime.now(UTC))

    errors = _graph_order_then_peer(pair, app_engine, waiting_case, peer)
    assert errors == [None, None], errors


def test_regression_guard_the_old_add_reply_order_deadlocks(pair, app_engine, waiting_case):
    """Regression guard: the old add_reply order (customer, then case) against the graph's
    (case, then customer) deadlocks."""

    def old_add_reply(session, customer_held):
        session.scalar(
            select(Customer).where(Customer.id == waiting_case["customer_id"]).with_for_update()
        )
        customer_held.set()
        session.scalar(select(Case).where(Case.id == waiting_case["case_id"]).with_for_update())

    errors = _graph_order_then_peer(pair, app_engine, waiting_case, old_add_reply)
    assert sum(_is_deadlock(e) for e in errors) == 1, errors
