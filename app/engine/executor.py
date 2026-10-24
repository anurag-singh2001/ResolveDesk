"""Safe refund execution: PROJECT.md section 10, steps 1-5.

1. Load the proposal and its approval; refuse unless usable (approved, not expired, hash
   intact, bound to this proposal).
2. Short transaction: lock the order row (SELECT ... FOR UPDATE), re-check eligibility and
   the refundable balance, insert the execution and the `reserved` ledger row under the stable
   key `P-<proposal_id>:refund:1`, commit.
3. Call the payment connector with that key, outside any transaction.
4. Persist the outcome in a second short transaction. A timeout is `unknown`: never assumed.
5. Re-running (retry, crash recovery, a second worker) never mints a new key: it reconciles
   by key first and only re-sends with the same key if the provider has no record of it.

The database backs all of this up: one execution and one reservation per proposal, an
execution must reference an approved approval of the same proposal, and a reservation must
match its proposal's amount and order.
"""

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.actions.base import get_action
from app.connectors.base import RefundOutcome, connector_for
from app.core import audit
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    DomainEvent,
    Execution,
    Payment,
    RefundOperation,
)
from app.core.tenancy import TenantContext
from app.engine.approvals import Usability, check_usable
from app.engine.eligibility import CAPTURED_STATUSES, order_facts

TERMINAL = ("succeeded", "failed")
# provider outcome -> (execution status, ledger status)
STATUS_MAP = {
    "succeeded": ("succeeded", "succeeded"),
    "failed": ("failed", "failed"),
    "processing": ("processing", "submitted"),
    "unknown": ("unknown", "unknown"),
    "unavailable": ("submitted", "reserved"),  # nothing applied; same-key retry is safe
}


class ExecutionRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RefundResult:
    """Only provider-confirmed states. `unknown` means: we don't know yet (hard rule 7)."""

    status: str  # submitted | processing | succeeded | failed | unknown
    idempotency_key: str
    provider_reference: str | None = None


def refund_key(proposal_id: uuid.UUID) -> str:
    return f"P-{proposal_id}:refund:1"


@dataclass(frozen=True)
class _Job:
    key: str
    payment_reference: str
    amount_paise: int
    settings: dict
    fresh: bool  # reserved just now (no provider call made yet)


def execute_refund(
    engine: Engine,
    ctx: TenantContext,
    proposal_id: uuid.UUID,
    now: datetime | None = None,
    unavailable_retries: int = 2,
) -> RefundResult:
    now = now or datetime.now(UTC)
    job = _reserve(engine, ctx, proposal_id, now)
    if isinstance(job, RefundResult):  # already finished earlier
        return job
    connector = connector_for(job.settings, "payment")
    # Steps 3-5. No DB transaction is open from here on (hard rule 5).
    if not job.fresh:
        # Resuming: money may already be in flight. Ask the provider by key before anything.
        found = connector.find_refund(ctx, job.key)
        if found is not None and found.status == "unavailable":
            return _current(engine, ctx, proposal_id)  # can't tell yet: reconcile later
        if found is not None:
            return _persist(engine, ctx, proposal_id, job.key, found)
        # The provider has no record, so nothing is in flight: this send is the first one
        # that can move money, and the approval must still be usable for it.
        usable = _still_usable(engine, ctx, proposal_id, now)
        if not usable.ok:
            _release(engine, ctx, proposal_id, usable.reason)
            raise ExecutionRefused(usable.reason)
    outcome = _send(connector, ctx, job, unavailable_retries)
    return _persist(engine, ctx, proposal_id, job.key, outcome)


def reconcile_refund(engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID) -> RefundResult:
    """For executions left `unknown`/`submitted`/`processing`: ask the provider by key."""
    current = _current(engine, ctx, proposal_id)
    if current.status in TERMINAL:
        return current
    return execute_refund(engine, ctx, proposal_id)


def _send(connector, ctx, job: "_Job", retries: int) -> RefundOutcome:
    """Same key every attempt. Transient errors (nothing applied) back off briefly."""
    outcome = connector.refund(ctx, job.key, job.payment_reference, job.amount_paise)
    for attempt in range(1, retries + 1):
        if outcome.status != "unavailable":
            break
        time.sleep(0.2 * attempt)
        outcome = connector.refund(ctx, job.key, job.payment_reference, job.amount_paise)
    return outcome


RESERVE_RACE_CONSTRAINTS = {
    "uq_executions_one_per_proposal",
    "uq_refund_operations_one_per_proposal",
    "uq_executions_key",
    "uq_refund_operations_key",
}


def _reserve(engine, ctx, proposal_id, now) -> "_Job | RefundResult":
    try:
        return _reserve_once(engine, ctx, proposal_id, now)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint not in RESERVE_RACE_CONSTRAINTS:
            raise
        # Another worker reserved this proposal first (the order lock should prevent it):
        # resume theirs instead of creating a second one.
        return _reserve_once(engine, ctx, proposal_id, now)


def _current(engine, ctx, proposal_id) -> RefundResult:
    with tenant_session(ctx.tenant_id, engine) as s:
        execution = s.scalar(select(Execution).where(Execution.proposal_id == proposal_id))
        if execution is None:
            raise ExecutionRefused("not_started")
        return RefundResult(
            execution.status, execution.idempotency_key, execution.provider_reference
        )


def _still_usable(engine, ctx, proposal_id, now) -> Usability:
    with tenant_session(ctx.tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        approval = s.scalar(select(Approval).where(Approval.proposal_id == proposal_id))
        return check_usable(approval, proposal, now)


def _release(engine, ctx, proposal_id, reason: str) -> None:
    """Nothing was ever applied and the approval is no longer usable: fail the execution and
    free the reserved balance (failed rows don't hold money)."""
    with tenant_session(ctx.tenant_id, engine) as s:
        s.execute(
            update(Execution)
            .where(Execution.proposal_id == proposal_id, Execution.status.notin_(TERMINAL))
            .values(status="failed", error=f"released: {reason}")
        )
        s.execute(
            update(RefundOperation)
            .where(
                RefundOperation.proposal_id == proposal_id, RefundOperation.status.notin_(TERMINAL)
            )
            .values(status="failed")
        )
        audit.record(
            s,
            ctx.tenant_id,
            actor_type="system",
            actor_id=None,
            event="refund.released",
            entity_type="proposal",
            entity_id=proposal_id,
            payload={"reason": reason},
        )


def _reserve_once(engine, ctx, proposal_id, now) -> "_Job | RefundResult":
    with tenant_session(ctx.tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        if proposal is None or proposal.action != "refund":
            raise ExecutionRefused("not_found")
        params = proposal.params
        order_id = uuid.UUID(params["transaction_id"])
        amount = params["amount_paise"]  # from the hashed params, never a separate column
        # Lock the order first: every reservation for it queues here (balance check + insert
        # happen while no other transaction can reserve against the same order).
        order, facts = order_facts(s, order_id, lock=True, exclude_proposal=proposal.id)
        existing = s.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
        if existing is not None:
            if existing.status in TERMINAL:
                return RefundResult(
                    existing.status, existing.idempotency_key, existing.provider_reference
                )
            return _Job(
                existing.idempotency_key,
                _payment_reference(s, order.id),
                amount,
                facts.settings,
                fresh=False,
            )

        approval = s.scalar(select(Approval).where(Approval.proposal_id == proposal.id))
        usable = check_usable(approval, proposal, now)
        if not usable.ok:
            raise ExecutionRefused(usable.reason)
        action = get_action("refund")()
        inp = action.Input.model_validate_json(json.dumps(params))
        result = action.validate(ctx, inp, facts)
        if not result.ok:  # e.g. another refund used the balance since approval
            raise ExecutionRefused("not_eligible: " + "; ".join(result.errors))

        key = refund_key(proposal.id)
        s.add(
            Execution(
                tenant_id=ctx.tenant_id,
                proposal_id=proposal.id,
                approval_id=approval.id,
                idempotency_key=key,
                status="submitted",
            )
        )
        s.add(
            RefundOperation(
                tenant_id=ctx.tenant_id,
                transaction_id=order.id,
                proposal_id=proposal.id,
                idempotency_key=key,
                amount_paise=amount,
                status="reserved",
            )
        )
        audit.record(
            s,
            ctx.tenant_id,
            actor_type="system",
            actor_id=None,
            event="refund.reserved",
            entity_type="proposal",
            entity_id=proposal.id,
            payload={"amount_paise": amount, "checks": result.checks},
        )
        s.flush()
        return _Job(key, _payment_reference(s, order.id), amount, facts.settings, fresh=True)


def _payment_reference(session, order_id) -> str:
    ref = session.scalar(
        select(Payment.provider_reference)
        .where(Payment.transaction_id == order_id, Payment.status.in_(CAPTURED_STATUSES))
        .order_by(Payment.amount_paise.desc())
        .limit(1)
    )
    if ref is None:
        raise ExecutionRefused("no_captured_payment")
    return ref


def _persist(engine, ctx, proposal_id, key, outcome: RefundOutcome) -> RefundResult:
    """Record the provider's answer. Never downgrades a finished execution (a slower worker's
    stale answer is ignored) and never erases a known provider reference."""
    exec_status, ledger_status = STATUS_MAP[outcome.status]
    ref = {"provider_reference": outcome.provider_reference} if outcome.provider_reference else {}
    with tenant_session(ctx.tenant_id, engine) as s:
        changed = s.execute(
            update(Execution)
            .where(Execution.proposal_id == proposal_id, Execution.status.notin_(TERMINAL))
            .values(status=exec_status, error=outcome.failure_reason, **ref)
        ).rowcount
        s.execute(
            update(RefundOperation)
            .where(
                RefundOperation.proposal_id == proposal_id, RefundOperation.status.notin_(TERMINAL)
            )
            .values(status=ledger_status, **ref)
        )
        if changed:
            audit.record(
                s,
                ctx.tenant_id,
                actor_type="system",
                actor_id=None,
                event=f"refund.{exec_status}",
                entity_type="proposal",
                entity_id=proposal_id,
                payload={"provider_status": outcome.status},
            )
            if exec_status in TERMINAL:
                s.add(
                    DomainEvent(
                        tenant_id=ctx.tenant_id,
                        event=f"refund.{exec_status}",
                        entity_id=proposal_id,
                        payload={"idempotency_key": key},
                    )
                )
        current = s.scalar(select(Execution).where(Execution.proposal_id == proposal_id))
        return RefundResult(current.status, key, current.provider_reference)
