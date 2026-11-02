"""Run scenarios through an agent pipeline and record what happened (PROJECT.md section 16).

Per scenario: pick the order its selector names (from the seeded history), open a free-text
case on it for that order's customer, run the pipeline (real LLMs), then read the result
back from the database. The business-rule ceiling is computed by code from the *expected*
category, so scoring never depends on what the model said.

Orders: a pass never reuses an order, and skips orders that had a case before it started.
Pipelines don't reserve money until a refund is approved and executed (nothing is approved
here), so a second pipeline can reuse the same orders: both are scored on the same cases.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as clock_time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.actions.base import get_action
from app.core.business_time import DEFAULT_TIMEZONE
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Case,
    Fulfilment,
    LineItem,
    Payment,
    Ticket,
    TicketMessage,
    Transaction,
)
from app.core.tenancy import tenant_id_for
from app.engine.eligibility import order_facts
from app.engine.resolver import decide_remedy
from evals.scenarios import OrderSelector, Scenario

# run(engine, tenant_id, case_id, message, pipeline) -> run_case's result dict
Runner = Callable[[Engine, uuid.UUID, uuid.UUID, str, str], dict]


@dataclass
class Ceiling:
    action: str | None
    amount: int | None  # the action's amount field (paise), None if it has none


@dataclass
class Result:
    scenario: Scenario
    pipeline: str
    order_id: str | None
    ceiling: Ceiling
    outcome: str = ""
    category: str | None = None
    action: str | None = None
    amount: int | None = None
    reason: str = ""
    llm: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str = ""
    case_id: str = ""


def existing_case_orders(engine: Engine, slug: str) -> set[uuid.UUID]:
    """Orders that already have a case: never picked (their history would leak in)."""
    with tenant_session(tenant_id_for(slug), engine) as s:
        return set(s.scalars(select(Case.transaction_id).where(Case.transaction_id.is_not(None))))


def _candidates(s: Session, skip: set[uuid.UUID]):
    """Completed, paid orders, newest first, as (order, fulfilment, minutes late)."""
    paid = select(Payment.transaction_id).where(
        Payment.status.in_(("captured", "partially_refunded"))
    )
    rows = s.execute(
        select(Transaction, Fulfilment)
        .join(Fulfilment, Fulfilment.transaction_id == Transaction.id)
        .where(
            Fulfilment.status == "completed",
            Fulfilment.completed_at.is_not(None),
            Transaction.id.in_(paid),
        )
        .order_by(Transaction.placed_at.desc(), Transaction.id)
    ).all()
    for order, f in rows:
        if order.id not in skip:
            yield order, f, int((f.completed_at - f.promised_at).total_seconds() // 60)


def _short_orders(s: Session) -> set[uuid.UUID]:
    """Orders with at least one item not delivered in full."""
    return set(
        s.scalars(
            select(LineItem.transaction_id)
            .where(LineItem.quantity_fulfilled < LineItem.quantity)
            .distinct()
        )
    )


def select_order(
    s: Session,
    sel: OrderSelector,
    skip: set[uuid.UUID],
    planted: list | None = None,
) -> Transaction | None:
    """The order a selector names (deterministic for a given seed). `shortfall` may mark one
    item of the newest order as not delivered when the history has none, and `placed_on`
    re-dates the pick; both are recorded in `planted` (undo_planted). `on_time` never picks a
    short order (it
    backs "nothing is missing" claims)."""
    if sel.select == "none":
        return None
    cands = list(_candidates(s, skip))
    if not cands:
        raise LookupError("no unused completed orders left")
    pick = None
    if sel.select == "latest":
        pick = cands[0][0]
    elif sel.select == "most_late":
        pick = max(cands, key=lambda c: c[2])[0]
    elif sel.select == "late_between":
        pick = next((o for o, _, m in cands if sel.min_minutes <= m <= sel.max_minutes), None)
    elif sel.select == "on_time":
        short = _short_orders(s)
        pick = next((o for o, _, m in cands if m <= 0 and o.id not in short), None)
    elif sel.select == "flagged":
        pick = next((o for o, f, _ in cands if f.attributes.get(sel.flag)), cands[0][0])
    elif sel.select == "shortfall":
        short = _short_orders(s)
        pick = next((o for o, _, _ in cands if o.id in short), None)
        if pick is None:
            pick = cands[0][0]
            line = s.scalars(
                select(LineItem)
                .where(LineItem.transaction_id == pick.id)
                .order_by(LineItem.unit_price_paise.desc(), LineItem.id)
                .limit(1)
            ).one()
            s.execute(
                update(LineItem)
                .where(LineItem.id == line.id)
                .values(quantity_fulfilled=line.quantity - 1)
            )
            if planted is not None:
                planted.append(("line", line.id, None))
    if pick is None:
        raise LookupError(f"no order matches selector {sel.model_dump(exclude_none=True)}")
    if sel.placed_on is not None:
        _redate(s, pick, sel.placed_on, planted)
    return pick


def _redate(s: Session, order: Transaction, placed_on: date, planted: list | None) -> None:
    """Move an order (and its fulfilment and payments) to noon of `placed_on` in the tenant's
    business timezone, keeping every interval (so lateness is unchanged). Lets a scenario
    exercise rules dated after the generated history ends."""
    _, facts = order_facts(s, order.id)
    tz = ZoneInfo(facts.settings.get("business_timezone") or DEFAULT_TIMEZONE)
    delta = datetime.combine(placed_on, clock_time(12), tz) - order.placed_at
    s.execute(update(Transaction).where(Transaction.id == order.id)
              .values(placed_at=Transaction.placed_at + delta))  # fmt: skip
    s.execute(update(Fulfilment).where(Fulfilment.transaction_id == order.id)
              .values(promised_at=Fulfilment.promised_at + delta,
                      completed_at=Fulfilment.completed_at + delta))  # fmt: skip
    s.execute(update(Payment).where(Payment.transaction_id == order.id)
              .values(captured_at=Payment.captured_at + delta))  # fmt: skip
    s.refresh(order)
    if planted is not None:
        planted.append(("redate", order.id, delta))


def undo_planted(s: Session, planted: list) -> None:
    """Reverse what select_order changed (tests clean up their database with this)."""
    for kind, ref, delta in reversed(planted):
        if kind == "line":
            line = s.get(LineItem, ref)
            s.execute(update(LineItem).where(LineItem.id == ref)
                      .values(quantity_fulfilled=line.quantity))  # fmt: skip
        else:
            s.execute(update(Transaction).where(Transaction.id == ref)
                      .values(placed_at=Transaction.placed_at - delta))  # fmt: skip
            s.execute(update(Fulfilment).where(Fulfilment.transaction_id == ref)
                      .values(promised_at=Fulfilment.promised_at - delta,
                              completed_at=Fulfilment.completed_at - delta))  # fmt: skip
            s.execute(update(Payment).where(Payment.transaction_id == ref)
                      .values(captured_at=Payment.captured_at - delta))  # fmt: skip


def ceiling_for(s: Session, category: str | None, order_id: uuid.UUID | None) -> Ceiling:
    """The tenant's business rule for this category and order: the most any pipeline may
    propose. decide_remedy only reads these two attributes of the case."""
    if category is None or order_id is None:
        return Ceiling(None, None)
    r = decide_remedy(s, SimpleNamespace(category=category, transaction_id=order_id))
    if r.action is None:
        return Ceiling(None, None)
    amount_field = get_action(r.action).amount_field
    return Ceiling(r.action, r.params.get(amount_field) if amount_field else None)


def open_case(s: Session, tid: uuid.UUID, order: Transaction | None, message: str) -> uuid.UUID:
    """A free-text case (no category) as POST /cases makes it in agents mode."""
    now = datetime.now(UTC)
    if order is None:  # no order named: the customer of the newest order writes in
        customer_id = s.scalar(
            select(Transaction.customer_id)
            .where(Transaction.tenant_id == tid)  # RLS already limits it; belt and braces
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        )
    else:
        customer_id = order.customer_id
    case_id = uuid.uuid4()
    order_id = order.id if order is not None else None
    s.add(Case(id=case_id, tenant_id=tid, customer_id=customer_id, transaction_id=order_id,
               category=None, status="investigating", channel="app", opened_at=now))  # fmt: skip
    s.flush()
    ticket_id = uuid.uuid4()
    s.add(Ticket(id=ticket_id, tenant_id=tid, customer_id=customer_id, transaction_id=order_id,
                 case_id=case_id, category="unknown", status="open", channel="app",
                 opened_at=now))  # fmt: skip
    s.flush()
    s.add(TicketMessage(tenant_id=tid, ticket_id=ticket_id, author="customer", body=message,
                        sent_at=now))  # fmt: skip
    return case_id


def _read_back(engine: Engine, tid: uuid.UUID, case_id: uuid.UUID, res: Result) -> None:
    """Copy what the pipeline left (category, newest proposal) into the result. A case that is
    gone means something else wrote to this database during the run (a concurrent reseed or
    test cleanup): an error for this scenario, not a crash of the whole run."""
    with tenant_session(tid, engine) as s:
        case = s.get(Case, case_id)
        if case is None:
            res.outcome = "error"
            res.error = res.error or "case disappeared during the run (database shared?)"
            return
        res.category = case.category
        p = s.scalars(
            select(ActionProposal)
            .where(ActionProposal.case_id == case_id)
            .order_by(ActionProposal.created_at.desc())
            .limit(1)
        ).one_or_none()
        if p is not None:
            res.action = p.action
            amount_field = get_action(p.action).amount_field
            res.amount = p.params.get(amount_field) if amount_field else None


def run_scenarios(
    engine: Engine,
    slug: str,
    scenarios: list[Scenario],
    pipeline: str,
    run: Runner,
    skip: set[uuid.UUID],
    pause_seconds: float = 0.0,
    planted: list | None = None,
) -> list[Result]:
    tid = tenant_id_for(slug)
    used: set[uuid.UUID] = set()
    results = []
    for sc in scenarios:
        try:
            with tenant_session(tid, engine) as s:
                order = select_order(s, sc.order, skip | used, planted)
                if order is not None:
                    used.add(order.id)
                order_id = order.id if order is not None else None
                ceiling = ceiling_for(s, sc.expect.category, order_id)
                case_id = open_case(s, tid, order, sc.message)
        except Exception as exc:  # bookkeeping failed: this scenario is an error, the run goes on
            res = Result(sc, pipeline, None, Ceiling(None, None), outcome="error")
            res.error = f"setup failed, {type(exc).__name__}: {str(exc)[:160]}"
            results.append(res)
            continue
        res = Result(sc, pipeline, str(order_id) if order_id else None, ceiling)
        res.case_id = str(case_id)
        started = time.perf_counter()
        try:  # no DB transaction is open here: the pipeline opens its own
            out = run(engine, tid, case_id, sc.message, pipeline)
            res.outcome, res.reason, res.llm = (
                out.get("outcome", ""),
                out.get("reason", ""),
                (out.get("llm") or {}),
            )
        except Exception as exc:  # recorded as a failure, the run goes on
            res.outcome, res.error = "error", f"{type(exc).__name__}: {str(exc)[:200]}"
        res.seconds = time.perf_counter() - started
        try:
            _read_back(engine, tid, case_id, res)
        except Exception as exc:
            res.outcome = "error"
            res.error = res.error or f"read-back failed, {type(exc).__name__}: {str(exc)[:160]}"
        results.append(res)
        if pause_seconds:
            time.sleep(pause_seconds)  # free-tier rate limits (tokens per minute)
    return results
