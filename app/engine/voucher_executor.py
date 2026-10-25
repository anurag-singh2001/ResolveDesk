"""Voucher execution: the refund recipe (executor.py) without a money ledger.

1. Short transaction: lock the proposal's execution slot, refuse unless the approval is usable,
   re-check eligibility, insert the execution (`submitted`) under the stable key
   `P-<proposal_id>:voucher:1`, commit.
2. Call the voucher connector with that key, outside any transaction.
3. Persist the answer, moving forward only. A timeout is `unknown`, never "issued".
4. Resuming (retry, sweeper, second worker) asks the provider by key first, and only re-sends
   (same key) while the approval is still usable.

The case is `resolved` only once the provider confirms the voucher (hard rule 7).
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
from app.connectors.base import VoucherOutcome, connector_for
from app.core import audit
from app.core.db import tenant_session
from app.core.models import ActionProposal, Approval, Case, DomainEvent, Execution
from app.core.tenancy import TenantContext
from app.engine.approvals import check_usable, evaluate_proposal
from app.engine.executor import EXEC_FORWARD, RESERVE_RACE_CONSTRAINTS, TERMINAL, ExecutionRefused

ACTION = "free_item_voucher"
# provider outcome -> execution status
STATUS_MAP = {
    "succeeded": "succeeded",
    "failed": "failed",
    "processing": "processing",
    "unknown": "unknown",
    "unavailable": "submitted",  # nothing applied; same-key retry is safe
}
# Case statuses an execution result may move on from (a person may have taken it over).
CASE_OPEN = ("executing", "awaiting_approval")


@dataclass(frozen=True)
class VoucherResult:
    status: str  # submitted | processing | succeeded | failed | unknown
    idempotency_key: str
    provider_reference: str | None = None


@dataclass(frozen=True)
class _Job:
    key: str
    customer_reference: str
    order_reference: str
    value_paise: int
    settings: dict
    fresh: bool


def voucher_key(proposal_id: uuid.UUID) -> str:
    return f"P-{proposal_id}:voucher:1"


def execute_voucher(
    engine: Engine,
    ctx: TenantContext,
    proposal_id: uuid.UUID,
    now: datetime | None = None,
    unavailable_retries: int = 2,
) -> VoucherResult:
    now = now or datetime.now(UTC)
    job = _start(engine, ctx, proposal_id, now)
    if isinstance(job, VoucherResult):
        return job
    connector = connector_for(job.settings, "vouchers")
    # No DB transaction is open from here on (hard rule 5).
    if not job.fresh:
        found = connector.find_voucher(ctx, job.key)
        if found is not None and found.status == "unavailable":
            return _current(engine, ctx, proposal_id)
        if found is not None:
            return _persist(engine, ctx, proposal_id, job.key, found)
        with tenant_session(ctx.tenant_id, engine) as s:
            usable = check_usable(
                s.scalar(select(Approval).where(Approval.proposal_id == proposal_id)),
                s.get(ActionProposal, proposal_id),
                now,
            )
        if not usable.ok:
            # An earlier request may still land; record what we know and send nothing.
            _persist(engine, ctx, proposal_id, job.key, VoucherOutcome("unknown"))
            raise ExecutionRefused(usable.reason)
    outcome = connector.issue(
        ctx, job.key, job.customer_reference, job.order_reference, job.value_paise
    )
    for attempt in range(1, unavailable_retries + 1):
        if outcome.status != "unavailable":
            break
        time.sleep(0.2 * attempt)
        outcome = connector.issue(
            ctx, job.key, job.customer_reference, job.order_reference, job.value_paise
        )
    return _persist(engine, ctx, proposal_id, job.key, outcome)


def reconcile_voucher(
    engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID, now: datetime | None = None
) -> VoucherResult:
    current = _current(engine, ctx, proposal_id)
    if current.status in TERMINAL:
        return current
    return execute_voucher(engine, ctx, proposal_id, now)


def _start(engine, ctx, proposal_id, now) -> "_Job | VoucherResult":
    try:
        return _start_once(engine, ctx, proposal_id, now)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint not in RESERVE_RACE_CONSTRAINTS:
            raise
        return _start_once(engine, ctx, proposal_id, now)  # another worker started it: resume
    except ExecutionRefused as exc:
        if exc.reason.startswith("not_eligible"):  # final: re-running won't fix it
            _record_refusal(engine, ctx, proposal_id, exc.reason)
        raise


def _record_refusal(engine, ctx, proposal_id, reason: str) -> None:
    """An approved voucher the executor refuses for a reason re-running won't fix is recorded
    as a `failed` execution (never sent), like a refund: audit, domain event, and the caller
    escalates the case. A lapsed approval is not recorded (nothing was decided about it)."""
    with tenant_session(ctx.tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        approval = s.scalar(select(Approval).where(Approval.proposal_id == proposal_id))
        if proposal is None or approval is None or approval.decision != "approved":
            return
        s.scalar(select(Case.id).where(Case.id == proposal.case_id).with_for_update())
        if s.scalar(select(Execution.id).where(Execution.proposal_id == proposal_id)):
            return  # another worker already owns the execution
        s.add(
            Execution(
                tenant_id=ctx.tenant_id,
                proposal_id=proposal_id,
                approval_id=approval.id,
                idempotency_key=voucher_key(proposal_id),
                status="failed",
                error=f"refused: {reason}"[:500],
            )
        )
        audit.record(
            s,
            ctx.tenant_id,
            actor_type="system",
            actor_id=None,
            event="voucher.refused",
            entity_type="proposal",
            entity_id=proposal_id,
            payload={"reason": reason[:500], "sent": False},
        )
        s.add(
            DomainEvent(
                tenant_id=ctx.tenant_id,
                event="voucher.failed",
                entity_id=proposal_id,
                payload={"idempotency_key": voucher_key(proposal_id), "sent": False},
            )
        )


def _start_once(engine, ctx, proposal_id, now) -> "_Job | VoucherResult":
    with tenant_session(ctx.tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        if proposal is None or proposal.action != ACTION:
            raise ExecutionRefused("not_found")
        # The case row lock serialises workers on this proposal (vouchers have no order lock).
        case = s.scalar(select(Case).where(Case.id == proposal.case_id).with_for_update())
        params = proposal.params
        inp = get_action(ACTION)().Input.model_validate_json(json.dumps(params))
        existing = s.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
        if existing is not None and existing.status in TERMINAL:
            return VoucherResult(
                existing.status, existing.idempotency_key, existing.provider_reference
            )
        _, _, facts, result = evaluate_proposal(s, ctx, proposal, now)  # validate is identity-free
        job = _Job(
            key=existing.idempotency_key if existing else voucher_key(proposal.id),
            customer_reference=str(case.customer_id),  # from the case row, never from params
            order_reference=str(inp.transaction_id),
            value_paise=inp.value_paise,
            settings=facts.settings,
            fresh=existing is None,
        )
        if existing is not None:
            return job
        approval = s.scalar(select(Approval).where(Approval.proposal_id == proposal.id))
        usable = check_usable(approval, proposal, now)
        if not usable.ok:
            raise ExecutionRefused(usable.reason)
        if not result.ok:
            raise ExecutionRefused("not_eligible: " + "; ".join(result.errors))
        s.add(
            Execution(
                tenant_id=ctx.tenant_id,
                proposal_id=proposal.id,
                approval_id=approval.id,
                idempotency_key=job.key,
                status="submitted",
            )
        )
        audit.record(
            s,
            ctx.tenant_id,
            actor_type="system",
            actor_id=None,
            event="voucher.submitted",
            entity_type="proposal",
            entity_id=proposal.id,
            payload={"value_paise": inp.value_paise, "checks": result.checks},
        )
        s.flush()
        return job


def _current(engine, ctx, proposal_id) -> VoucherResult:
    with tenant_session(ctx.tenant_id, engine) as s:
        execution = s.scalar(select(Execution).where(Execution.proposal_id == proposal_id))
        if execution is None:
            raise ExecutionRefused("not_started")
        return VoucherResult(
            execution.status, execution.idempotency_key, execution.provider_reference
        )


def _persist(engine, ctx, proposal_id, key, outcome: VoucherOutcome) -> VoucherResult:
    """Forward-only write of the provider's answer; on a terminal answer, move the case."""
    status = STATUS_MAP[outcome.status]
    ref = {"provider_reference": outcome.provider_reference} if outcome.provider_reference else {}
    with tenant_session(ctx.tenant_id, engine) as s:
        changed = s.execute(
            update(Execution)
            .where(Execution.proposal_id == proposal_id, Execution.status.in_(EXEC_FORWARD[status]))
            .values(status=status, error=outcome.failure_reason, **ref)
        ).rowcount
        if changed:
            audit.record(
                s,
                ctx.tenant_id,
                actor_type="system",
                actor_id=None,
                event=f"voucher.{status}",
                entity_type="proposal",
                entity_id=proposal_id,
                payload={"provider_status": outcome.status},
            )
            if status in TERMINAL:
                case_id = s.scalar(
                    select(ActionProposal.case_id).where(ActionProposal.id == proposal_id)
                )
                s.execute(
                    update(Case)
                    .where(Case.id == case_id, Case.status.in_(CASE_OPEN))
                    .values(status="resolved" if status == "succeeded" else "escalated")
                )
                s.add(
                    DomainEvent(
                        tenant_id=ctx.tenant_id,
                        event=f"voucher.{status}",
                        entity_id=proposal_id,
                        payload={"idempotency_key": key},
                    )
                )
        current = s.scalar(select(Execution).where(Execution.proposal_id == proposal_id))
        return VoucherResult(current.status, key, current.provider_reference)
