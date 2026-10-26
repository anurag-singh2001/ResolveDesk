import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import Session

from app.actions.base import registered_actions
from app.api.deps import get_clock, get_db_engine, not_found, require_staff, tenant_db
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Location,
    Ticket,
    TicketMessage,
    Transaction,
)
from app.core.tenancy import TenantContext
from app.engine import approvals as engine_approvals
from app.engine.agent_runner import resume_after_decision
from app.engine.approvals import AlreadyDecided, Forbidden, NotEligible, NotFound, decide
from app.engine.dispatch import executable, run_approved
from app.engine.dispatch import reconcile as reconcile_execution
from app.engine.release import check_release, release_refund

router = APIRouter(tags=["approvals"])
log = logging.getLogger(__name__)


class CitationOut(BaseModel):
    section_ref: str
    doc_key: str | None = None
    version: int | None = None


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
    created_at: datetime
    # The customer's own words (their first message on the case), shown to staff as text.
    customer_message: str | None
    location_name: str | None
    citations: list[CitationOut]


def _citations(raw: object) -> list[CitationOut]:
    """Stored proposal citations, keeping only well-formed entries (never the policy text)."""
    out = []
    for c in raw if isinstance(raw, list) else []:
        if isinstance(c, dict) and isinstance(c.get("section_ref"), str):
            version = c.get("version")
            out.append(
                CitationOut(
                    section_ref=c["section_ref"],
                    doc_key=c["doc_key"] if isinstance(c.get("doc_key"), str) else None,
                    version=version if type(version) is int else None,
                )
            )
    return out


def _customer_message(db: Session, case_id: uuid.UUID) -> str | None:
    return db.scalar(
        select(TicketMessage.body)
        .join(Ticket, Ticket.id == TicketMessage.ticket_id)
        .where(Ticket.case_id == case_id, TicketMessage.author == "customer")
        .order_by(TicketMessage.sent_at, TicketMessage.id)
        .limit(1)
    )


# A pending proposal has no stored expiry (an approval's expiry starts when someone decides), so
# "expiring_soon" ranks by age: the longest-waiting proposals are the ones closest to going stale.
_SORTS = {
    "oldest": (ActionProposal.created_at,),
    "newest": (ActionProposal.created_at.desc(),),
    "amount_desc": (ActionProposal.amount_paise.desc().nulls_last(), ActionProposal.created_at),
    "expiring_soon": (ActionProposal.created_at, ActionProposal.amount_paise.desc().nulls_last()),
}


@router.get("/approvals")
def pending_approvals(
    limit: int = Query(100, ge=1, le=500),
    location_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None, max_length=64),
    sort: Literal["oldest", "newest", "amount_desc", "expiring_soon"] = "oldest",
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> list[PendingOut]:
    """Undecided proposals in the caller's scope, with the code checks the approver needs.

    Optional filters: location_id (404 unless the caller may see it, so other tenants' and
    out-of-scope ids look the same) and action (any registered action name, else 422).
    """
    if action is not None and action not in registered_actions():
        raise HTTPException(422, "unknown action")
    if location_id is not None:
        exists = db.scalar(select(Location.id).where(Location.id == location_id))
        if exists is None or not ctx.can_see_location(location_id):
            raise not_found()
    query = (
        select(ActionProposal, Case, Transaction, Location.name)
        .join(Case, Case.id == ActionProposal.case_id)
        .outerjoin(Transaction, Transaction.id == Case.transaction_id)
        .outerjoin(Location, Location.id == Transaction.location_id)
        .outerjoin(Approval, Approval.proposal_id == ActionProposal.id)
        .where(Approval.id.is_(None))
    )
    if location_id is not None:
        query = query.where(Transaction.location_id == location_id)
    if action is not None:
        query = query.where(ActionProposal.action == action)
    query = query.order_by(*_SORTS[sort], ActionProposal.id).limit(limit)
    if ctx.role != "hq_owner":
        query = query.where(and_(Transaction.id.is_not(None), ctx.visible_orders()))
    out = []
    for proposal, case, order, location_name in db.execute(query).all():
        _, _, _, result = engine_approvals.evaluate_proposal(db, ctx, proposal, now)
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
                created_at=proposal.created_at,
                customer_message=_customer_message(db, case.id),
                location_name=location_name,
                citations=_citations(proposal.citations),
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


def run_execution(engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID, action: str) -> None:
    """Execute, then verify, through the single execution path (dispatch.run_approved ->
    lifecycle). Runs after the response, once the request's transaction has committed: the
    provider is never called while a DB transaction is open (hard rule 5). Refusals and
    escalations are recorded in the DB/audit; nothing is raised to anyone."""
    try:
        run_approved(engine, ctx.tenant_id, proposal_id, action)
    except Exception:
        log.exception("%s %s: execute/verify failed", action, proposal_id)


def _after_decision(
    engine, ctx: TenantContext, case_id, proposal_id, action: str, approved: bool
) -> None:
    """Resume the case's paused graph thread (its execute node uses the same single path).
    With no paused thread (deterministic path, or a checkpoint that can't be reached) fall
    back to run_execution. Both firing for one approval is safe: one stable key, one
    provider operation."""
    try:
        out = resume_after_decision(engine, ctx.tenant_id, case_id, proposal_id)
    except Exception:
        log.exception("case %s: resuming the workflow after the decision failed", case_id)
        out = {"outcome": "skipped"}
    if approved and out.get("outcome") == "skipped" and executable(action):
        run_execution(engine, ctx, proposal_id, action)


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
    approved = body.decision == "approved"
    queued = approved and executable(proposal.action)
    # Resume the case's paused workflow, or run the execution path: after this request
    # commits (always queued: a rejection must finish a paused thread too).
    background.add_task(
        _after_decision, engine, ctx, proposal.case_id, proposal_id, proposal.action, approved
    )
    return DecisionOut(
        proposal_id=proposal_id,
        decision=approval.decision,
        expires_at=approval.expires_at,
        execution="queued" if queued else "none",
    )


def _run_reconcile(engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID, action: str) -> None:
    try:
        reconcile_execution(engine, ctx.tenant_id, proposal_id, action)
    except Exception:
        log.exception("%s %s: reconcile/verify failed", action, proposal_id)


@router.post("/approvals/{proposal_id}/reconcile", status_code=status.HTTP_202_ACCEPTED)
def reconcile(
    proposal_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> dict[str, str]:
    """Ask the provider about an unfinished refund or voucher (e.g. after a timeout). Queued: the
    provider is only called after this request's transaction has ended (hard rule 5).
    Poll GET /cases/{id} for the result."""
    proposal = db.get(ActionProposal, proposal_id)
    if proposal is None or not executable(proposal.action):
        raise not_found()
    try:
        location = engine_approvals.proposal_location(db, proposal)
    except LookupError:
        raise not_found() from None
    if ctx.role != "hq_owner" and (location is None or not ctx.can_see_location(location)):
        raise not_found()
    background.add_task(_run_reconcile, engine, ctx, proposal_id, proposal.action)
    return {"status": "queued"}


def _run_release(engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID) -> None:
    result = release_refund(engine, ctx, proposal_id)
    log.info("release of %s: %s (%s)", proposal_id, result.outcome, result.reason)


@router.post("/approvals/{proposal_id}/release", status_code=status.HTTP_202_ACCEPTED)
def release(
    proposal_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> dict[str, str]:
    """hq_owner only: free a quarantined refund's held balance once the provider can no
    longer apply it. Checked here (DB only), then queued: the provider lookup by key runs
    after this request's transaction has ended (hard rule 5). If the provider has the
    refund, it is recorded instead of released. See GET /cases/{id}/events."""
    if ctx.role != "hq_owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hq_owner only")
    check = check_release(db, proposal_id, datetime.now(UTC))
    if check.reason == "not_found":
        raise not_found()
    if not check.ok:
        detail = {"reason": check.reason, "ledger_status": check.ledger_status}
        if check.ready_at is not None:
            detail["ready_at"] = check.ready_at.isoformat()
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
    background.add_task(_run_release, engine, ctx, proposal_id)
    return {"status": "queued"}
