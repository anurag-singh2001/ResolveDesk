"""Code-only case transitions shared by the deterministic path, the agent graph, the staff
decision route, the sweeper and reconcile: proposed -> (auto)approved -> executed -> verified,
or escalated. Each transition sets the case status and emits a domain event
(app.core.events) in the same transaction; subscribers (e.g. the customer update on the
ticket) react to the event, not to the engine.

ONE execution path (E4 integration): `execute_approved` is the only function that runs an
approved proposal (any action in dispatch.EXECUTORS). `execute_and_verify` is it plus the
verify step; `dispatch.run_approved` and `dispatch.reconcile` are thin calls into this
module. The graph's execute/verify nodes call the same functions, so a staff approval that
both resumes the paused graph and fires the decision fallback still sends one provider
operation (the executors serialise on the proposal and share one stable key).
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.db import tenant_session
from app.core.models import ActionProposal, Approval, Case, DomainEvent, Execution
from app.engine.approvals import auto_decide
from app.engine.dispatch import EXECUTORS, system_context
from app.engine.executor import ExecutionRefused
from app.engine.verifier import VerifyResult, verify_refund

log = logging.getLogger(__name__)

# Case statuses the engine may move to "escalated": never one a person already closed,
# resolved, or that is already escalated.
ESCALATABLE = ("open", "investigating", "awaiting_info", "awaiting_approval", "executing")


def proposal_made(
    session: Session, tenant_id: uuid.UUID, case: Case, proposal_id: uuid.UUID, now: datetime
) -> Approval | None:
    """After a proposal is stored: apply the auto-approve rule, set the case status, emit
    case.proposed (and case.approved when the rule approved it)."""
    approval = auto_decide(session, tenant_id, proposal_id, now)
    case.status = "executing" if approval is not None else "awaiting_approval"
    payload = {"proposal_id": str(proposal_id), "auto_approved": approval is not None}
    events.emit(session, tenant_id, "case.proposed", case.id, payload)
    if approval is not None:
        events.emit(session, tenant_id, "case.approved", case.id,
                    {"proposal_id": str(proposal_id), "mode": "auto"})  # fmt: skip
    return approval


def escalate(engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, reason: str) -> None:
    with tenant_session(tenant_id, engine) as s:
        case = s.get(Case, case_id)
        if case.status not in ESCALATABLE:  # a person already owns/closed it: never overwrite
            return
        case.status = "escalated"
        audit.record(s, tenant_id, actor_type="system", actor_id=None, event="case.escalated",
                     entity_type="case", entity_id=case_id,
                     payload={"reason": reason[:500]})  # fmt: skip
        events.emit(s, tenant_id, "case.escalated", case_id, {"reason": reason[:200]})


def execute_approved(
    engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, now: datetime | None = None
) -> str:
    """Execute step (code only), the single entry point for approved proposals. Returns
    executed | declined | escalated | pending (no approval committed yet) | approved (no
    executor for this action). Safe to repeat: every executor reuses its stable key and asks
    the provider by key before ever sending again. Never called inside a transaction."""
    with tenant_session(tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        if proposal is None:
            return "escalated"
        action, case_id = proposal.action, proposal.case_id
    if action not in EXECUTORS:
        return "approved"
    execute, _ = EXECUTORS[action]
    try:
        result = execute(engine, system_context(tenant_id), proposal_id, now=now)
    except ExecutionRefused as exc:
        if exc.reason == "rejected":
            return "declined"
        if exc.reason == "no_approval":  # ran before the decision committed: nothing to do
            return "pending"
        log.info("%s %s not executed: %s", action, proposal_id, exc.reason)
        escalate(engine, tenant_id, case_id, f"execution refused: {exc.reason}")
        return "escalated"
    _executed(engine, tenant_id, case_id, proposal_id, result)
    return "executed"


def verify_executed(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID) -> str:
    """Verify step. Returns resolved | escalated | processing (not final yet: reconcile).

    Refunds: the verifier re-reads the payment provider by key and compares status, amount
    and reference; the case is resolved only on success AND a verified verdict.
    Vouchers: there is no amount/reference ledger to compare, and the voucher executor's
    answer already IS the provider's record fetched by key (resume and reconcile ask the
    provider by key first). So the verdict is the provider-confirmed execution status; the
    voucher executor moved the case, and this step emits case.verified for the customer
    update. A timeout stays 'processing', never 'issued' (hard rule 7)."""
    with tenant_session(tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        if proposal is None:
            return "escalated"
        action, case_id = proposal.action, proposal.case_id
        status = s.scalar(select(Execution.status).where(Execution.proposal_id == proposal_id))
    if action == "refund":
        verdict: VerifyResult = verify_refund(engine, system_context(tenant_id), proposal_id)
        if verdict.status == "verified" and verdict.execution_status == "succeeded":
            return "resolved"
        if verdict.status in ("verified", "mismatch"):  # failed, or the records disagree
            return "escalated"
        return "processing"
    if status == "succeeded":
        with tenant_session(tenant_id, engine) as s:
            case = s.scalar(select(Case).where(Case.id == case_id).with_for_update())
            seen = s.scalar(
                select(DomainEvent.id).where(
                    DomainEvent.event == "case.verified",
                    DomainEvent.entity_id == case_id,
                    DomainEvent.payload["proposal_id"].as_string() == str(proposal_id),
                )
            )
            if case.status == "resolved" and seen is None:  # only on the transition
                events.emit(s, tenant_id, "case.verified", case_id,
                            {"proposal_id": str(proposal_id), "status": "confirmed"})  # fmt: skip
        return "resolved"
    if status == "failed":
        return "escalated"
    return "processing"


def execute_and_verify(
    engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, now: datetime | None = None
) -> str:
    """Both steps, for callers with no paused graph (the deterministic path, the decision
    fallback, auto-approval on open, the sweeper)."""
    outcome = execute_approved(engine, tenant_id, proposal_id, now)
    return verify_executed(engine, tenant_id, proposal_id) if outcome == "executed" else outcome


def reconcile_and_verify(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID) -> str:
    """For an execution left unknown/processing: ask the provider by key (never a new key,
    never a first send for a refund), then verify. A quarantined refund stays quarantined
    (no escalation here)."""
    with tenant_session(tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        if proposal is None or proposal.action not in EXECUTORS:
            return "processing"
        action, case_id = proposal.action, proposal.case_id
    _, reconcile = EXECUTORS[action]
    try:
        result = reconcile(engine, system_context(tenant_id), proposal_id)
    except ExecutionRefused as exc:
        log.info("%s %s not reconciled: %s", action, proposal_id, exc.reason)
        return "processing"
    _executed(engine, tenant_id, case_id, proposal_id, result)
    return verify_executed(engine, tenant_id, proposal_id)


def _executed(engine, tenant_id, case_id, proposal_id, result) -> None:
    with tenant_session(tenant_id, engine) as s:
        events.emit(s, tenant_id, "case.executed", case_id,
                    {"proposal_id": str(proposal_id), "status": result.status})  # fmt: skip
