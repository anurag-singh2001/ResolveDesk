import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db_engine, not_found, require_staff, tenant_db
from app.core.models import ActionProposal, Approval, Case, Transaction
from app.core.tenancy import TenantContext
from app.engine import approvals as engine_approvals
from app.engine.approvals import AlreadyDecided, Forbidden, NotEligible, NotFound, decide
from app.engine.executor import ExecutionRefused, execute_refund, reconcile_refund

router = APIRouter(tags=["approvals"])
log = logging.getLogger(__name__)


class PendingOut(BaseModel):
    proposal_id: uuid.UUID
    case_id: uuid.UUID
    category: str | None
    action: str
    risk: str
    amount_paise: int | None
    order_ref: str | None
    order_total_paise: int | None
    reason: str
    checks: dict
    eligible: bool
    errors: list[str]


@router.get("/approvals")
def pending_approvals(
    limit: int = Query(100, ge=1, le=500),
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> list[PendingOut]:
    """Undecided proposals in the caller's scope, with the code checks the approver needs."""
    query = (
        select(ActionProposal, Case, Transaction)
        .join(Case, Case.id == ActionProposal.case_id)
        .outerjoin(Transaction, Transaction.id == Case.transaction_id)
        .outerjoin(Approval, Approval.proposal_id == ActionProposal.id)
        .where(Approval.id.is_(None))
        .order_by(ActionProposal.created_at)
        .limit(limit)
    )
    if ctx.role != "hq_owner":
        query = query.where(and_(Transaction.id.is_not(None), ctx.visible_orders()))
    out = []
    for proposal, case, order in db.execute(query).all():
        _, _, _, result = engine_approvals.evaluate_proposal(db, ctx, proposal)
        out.append(
            PendingOut(
                proposal_id=proposal.id,
                case_id=case.id,
                category=case.category,
                action=proposal.action,
                risk=proposal.risk,
                amount_paise=proposal.amount_paise,
                order_ref=order.external_ref if order else None,
                order_total_paise=order.total_paise if order else None,
                reason=proposal.reason,
                checks=result.checks,
                eligible=result.ok,
                errors=result.errors,
            )
        )
    return out


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(None, max_length=500)


class DecisionOut(BaseModel):
    proposal_id: uuid.UUID
    decision: str
    expires_at: datetime
    execution: str  # what happens next: queued | none


def run_refund(engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID) -> None:
    """Runs after the response, once the request's transaction has committed: the provider
    is never called while a DB transaction is open (hard rule 5)."""
    try:
        execute_refund(engine, ctx, proposal_id)
    except ExecutionRefused as exc:  # recorded in the DB/audit; nothing to raise to anyone
        log.info("refund %s not executed: %s", proposal_id, exc.reason)


@router.post("/approvals/{proposal_id}/decision")
def post_decision(
    proposal_id: uuid.UUID,
    body: DecisionIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> DecisionOut:
    """`proposal_id`: an approval doesn't exist until this call creates it."""
    try:
        approval = decide(db, ctx, proposal_id, body.decision, datetime.now(UTC), body.note)
    except NotFound:
        raise not_found() from None
    except Forbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except AlreadyDecided:
        raise HTTPException(status.HTTP_409_CONFLICT, "already decided") from None
    except NotEligible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors) from None
    proposal = db.get(ActionProposal, proposal_id)
    queued = body.decision == "approved" and proposal.action == "refund"
    if queued:
        background.add_task(run_refund, engine, ctx, proposal_id)
    return DecisionOut(
        proposal_id=proposal_id,
        decision=approval.decision,
        expires_at=approval.expires_at,
        execution="queued" if queued else "none",
    )


def _run_reconcile(engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID) -> None:
    try:
        reconcile_refund(engine, ctx, proposal_id)
    except ExecutionRefused as exc:
        log.info("refund %s not reconciled: %s", proposal_id, exc.reason)


@router.post("/approvals/{proposal_id}/reconcile", status_code=status.HTTP_202_ACCEPTED)
def reconcile(
    proposal_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> dict[str, str]:
    """Ask the provider about an unfinished refund (e.g. after a timeout). Queued: the
    provider is only called after this request's transaction has ended (hard rule 5).
    Poll GET /cases/{id} for the result."""
    proposal = db.get(ActionProposal, proposal_id)
    if proposal is None or proposal.action != "refund":
        raise not_found()
    try:
        location = engine_approvals.proposal_location(db, proposal)
    except LookupError:
        raise not_found() from None
    if ctx.role != "hq_owner" and (location is None or not ctx.can_see_location(location)):
        raise not_found()
    background.add_task(_run_reconcile, engine, ctx, proposal_id)
    return {"status": "queued"}
