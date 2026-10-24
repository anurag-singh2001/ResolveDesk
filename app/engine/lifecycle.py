"""Code-only case transitions shared by the deterministic path and the agent graph:
proposed -> (auto)approved -> executed -> verified, or escalated. Each transition sets the
case status and emits a domain event (app.core.events) in the same transaction; subscribers
(e.g. the customer update on the ticket) react to the event, not to the engine.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.db import tenant_session
from app.core.models import ActionProposal, Approval, Case
from app.core.tenancy import TenantContext
from app.engine.approvals import auto_decide
from app.engine.executor import ExecutionRefused, RefundResult, execute_refund, reconcile_refund
from app.engine.verifier import VerifyResult, verify_refund

log = logging.getLogger(__name__)


def system_context(tenant_id: uuid.UUID) -> TenantContext:
    """The engine acting for a tenant (tenant from the auth/system context only). Only for
    code that ignores identity (executor, verifier, validate); never for scope checks."""
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a UUID from the auth/system context")
    return TenantContext(
        tenant_id, uuid.UUID(int=0), uuid.UUID(int=0), "hq_owner", frozenset(), frozenset()
    )


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
        case.status = "escalated"
        audit.record(s, tenant_id, actor_type="system", actor_id=None, event="case.escalated",
                     entity_type="case", entity_id=case_id,
                     payload={"reason": reason[:500]})  # fmt: skip
        events.emit(s, tenant_id, "case.escalated", case_id, {"reason": reason[:200]})


def execute_approved(
    engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, now: datetime | None = None
) -> str:
    """Execute step (code only). Returns executed | declined | escalated | approved (no
    executor for this action yet, E4.6). Safe to repeat: the executor reuses its stable key
    and reconciles by key before ever sending again."""
    with tenant_session(tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        if proposal is None:
            return "escalated"
        action, case_id = proposal.action, proposal.case_id
    if action != "refund":
        return "approved"
    try:
        result = execute_refund(engine, system_context(tenant_id), proposal_id, now=now)
    except ExecutionRefused as exc:
        if exc.reason == "rejected":
            return "declined"
        log.info("refund %s not executed: %s", proposal_id, exc.reason)
        escalate(engine, tenant_id, case_id, f"execution refused: {exc.reason}")
        return "escalated"
    _executed(engine, tenant_id, case_id, proposal_id, result)
    return "executed"


def verify_executed(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID) -> str:
    """Verify step. Returns resolved | escalated | processing (not final yet: reconcile)."""
    verdict: VerifyResult = verify_refund(engine, system_context(tenant_id), proposal_id)
    if verdict.status == "verified" and verdict.execution_status == "succeeded":
        return "resolved"
    if verdict.status in ("verified", "mismatch"):  # failed, or the records disagree
        return "escalated"
    return "processing"


def execute_and_verify(
    engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, now: datetime | None = None
) -> str:
    """Both steps, for cases with no paused graph (the deterministic path, reconcile)."""
    outcome = execute_approved(engine, tenant_id, proposal_id, now)
    return verify_executed(engine, tenant_id, proposal_id) if outcome == "executed" else outcome


def reconcile_and_verify(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID) -> str:
    """For a refund left unknown/processing: ask the provider by key (never a new key, never
    a first send), then verify. A quarantined refund stays quarantined (no escalation here)."""
    try:
        result = reconcile_refund(engine, system_context(tenant_id), proposal_id)
    except ExecutionRefused as exc:
        log.info("refund %s not reconciled: %s", proposal_id, exc.reason)
        return "processing"
    with tenant_session(tenant_id, engine) as s:
        case_id = s.get(ActionProposal, proposal_id).case_id
    _executed(engine, tenant_id, case_id, proposal_id, result)
    return verify_executed(engine, tenant_id, proposal_id)


def _executed(engine, tenant_id, case_id, proposal_id, result: RefundResult) -> None:
    with tenant_session(tenant_id, engine) as s:
        events.emit(s, tenant_id, "case.executed", case_id,
                    {"proposal_id": str(proposal_id), "status": result.status})  # fmt: skip
