import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import Session

from app.actions.base import registered_actions
from app.api.decision_sources import SourceOut, decision_sources
from app.api.deps import get_clock, get_db_engine, not_found, require_staff, tenant_db
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Location,
    Transaction,
    User,
)
from app.core.tenancy import TenantContext
from app.engine import approvals as engine_approvals
from app.engine.agent_runner import resume_after_decision
from app.engine.approvals import (
    AlreadyDecided,
    Forbidden,
    NotEligible,
    NotFound,
    WaitingForCustomer,
    decide,
)
from app.engine.case_messages import first_customer_message
from app.engine.dispatch import executable, run_approved
from app.engine.dispatch import reconcile as reconcile_execution
from app.engine.offer_state import queue_reasons
from app.engine.offer_view import staff_offer
from app.engine.release import check_release, release_refund
from app.engine.switch import alternatives as switch_alternatives
from app.engine.switch import switch_remedy

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
    # Staff who proposed it (S7.5), by name; None for an engine proposal. An erased or unknown
    # user shows as "Former staff member".
    proposed_by_name: str | None = None
    location_name: str | None
    citations: list[CitationOut]
    # S8.3: the rule that set the amount (plain lines) and the cited sections as links.
    basis: list[str] = []
    sources: list[SourceOut] = []
    # S8.10: the question put to the customer, if any ("open" means: waiting for the customer).
    offer: dict | None = None
    # S8.10: why a person sees this one now: customer_chose | no_customer_answer | None.
    queue_reason: str | None = None


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


# Sorts over stored columns only: a pending proposal has no expiry yet (an approval's 4-hour
# clock starts when someone decides), so there is deliberately no "expiring soon" sort.

# A pending proposal has no stored expiry (an approval's expiry starts when someone decides), so
_SORTS = {
    "oldest": (ActionProposal.created_at,),
    "newest": (ActionProposal.created_at.desc(),),
    "amount_desc": (ActionProposal.amount_paise.desc().nulls_last(), ActionProposal.created_at),
}


@router.get("/approvals")
def pending_approvals(
    limit: int = Query(100, ge=1, le=500),
    location_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None, max_length=64),
    sort: Literal["oldest", "newest", "amount_desc"] = "oldest",
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
        .where(Approval.id.is_(None), engine_approvals.not_superseded())
    )
    if location_id is not None:
        query = query.where(Transaction.location_id == location_id)
    if action is not None:
        query = query.where(ActionProposal.action == action)
    query = query.order_by(*_SORTS[sort], ActionProposal.id).limit(limit)
    if ctx.role != "hq_owner":
        query = query.where(and_(Transaction.id.is_not(None), ctx.visible_orders()))
    out = []
    rows = db.execute(query).all()
    proposers = {p.proposed_by for p, *_ in rows if p.proposed_by}
    names = {
        uid: name if erased is None else "Former staff member"
        for uid, name, erased in db.execute(
            select(User.id, User.display_name, User.erased_at).where(User.id.in_(proposers))
        ).all()
    }
    # One clock for every read of an open question: the gate in decide() uses real time, so
    # the dev-clock offset must not make the screen offer Approve while the gate says wait.
    real_now = datetime.now(UTC)
    offer_reasons = queue_reasons(db, [p.id for p, *_ in rows], real_now)
    for proposal, case, order, location_name in rows:
        _, _, _, result = engine_approvals.evaluate_proposal(db, ctx, proposal, now)
        why = decision_sources(db, ctx, proposal, "en")  # staff read English
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
                customer_message=first_customer_message(db, case.id),
                proposed_by_name=(
                    names.get(proposal.proposed_by, "Former staff member")
                    if proposal.proposed_by
                    else None
                ),
                location_name=location_name,
                citations=_citations(proposal.citations),
                basis=why.basis,
                sources=why.sources,
                offer=staff_offer(db, proposal.id, real_now),
                queue_reason=offer_reasons.get(proposal.id),
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
    except WaitingForCustomer:
        raise HTTPException(status.HTTP_409_CONFLICT, "waiting for the customer") from None
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


class AlternativeOut(BaseModel):
    action: str
    min_paise: int
    max_paise: int
    step_paise: int
    needs_hq_above_paise: int | None
    you_can_approve_up_to_paise: int


class AlternativesOut(BaseModel):
    proposal_id: uuid.UUID
    current_action: str
    current_amount_paise: int | None
    alternatives: list[AlternativeOut]


@router.get("/approvals/{proposal_id}/alternatives")
def get_alternatives(
    proposal_id: uuid.UUID,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> AlternativesOut:
    """The remedies the rules allow for this pending proposal's case, with the amount range of
    each. A guide for the screen: POST /switch re-checks everything."""
    try:
        proposal, options = switch_alternatives(db, ctx, proposal_id)
    except NotFound:
        raise not_found() from None
    except AlreadyDecided:
        raise HTTPException(status.HTTP_409_CONFLICT, "no longer pending") from None
    except NotEligible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors) from None
    return AlternativesOut(
        proposal_id=proposal.id,
        current_action=proposal.action,
        current_amount_paise=proposal.amount_paise,
        alternatives=[AlternativeOut(**vars(o)) for o in options],
    )


class SwitchIn(BaseModel):
    action: str = Field(max_length=64)
    # A request, never a fact: strict int, then checked against the rule's range server-side.
    amount_paise: int | None = Field(None, strict=True, gt=0)
    approve: bool = False
    note: str = Field(max_length=500)  # the why, audited (blank is refused: 422)
    # hq_owner only: approve a raise yourself (up to the tenant's small limit) when there is no
    # second person. Needs a written reason; audited as self_approved.
    self_approve_reason: str | None = Field(None, max_length=500)


class SwitchOut(BaseModel):
    old_proposal_id: uuid.UUID
    proposal_id: uuid.UUID
    action: str
    amount_paise: int | None
    decision: str | None  # approved, or None while it waits for an approver
    # hq_owner: above what the caller may approve; second_person: the caller authored it, so
    # someone else must approve (unless a downgrade or a small owner override)
    waiting_for: str | None
    self_approved: str | None = None  # downgrade | owner_override
    expires_at: datetime | None
    execution: str  # queued | none


@router.post("/approvals/{proposal_id}/switch")
def post_switch(
    proposal_id: uuid.UUID,
    body: SwitchIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> SwitchOut:
    """Supersede a pending proposal with another allowed remedy (S7.10). 404 out of scope or
    another tenant, 409 not pending (decided, or already switched), 422 outside the rule.
    The caller authors the new proposal, so they cannot approve it, except `approve: true` on a
    downgrade, or an hq_owner's `self_approve_reason` up to the tenant's small limit; otherwise
    it stays pending for a different approver (`waiting_for`)."""
    try:
        result = switch_remedy(
            db,
            ctx,
            proposal_id,
            action=body.action,
            amount_paise=body.amount_paise,
            approve=body.approve,
            note=body.note,
            now=datetime.now(UTC),
            self_approve_reason=body.self_approve_reason,
        )
    except NotFound:
        raise not_found() from None
    except WaitingForCustomer:
        raise HTTPException(status.HTTP_409_CONFLICT, "waiting for the customer") from None
    except AlreadyDecided:
        raise HTTPException(status.HTTP_409_CONFLICT, "no longer pending") from None
    except Forbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except NotEligible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors) from None
    new = result.proposal
    queued = result.approval is not None and executable(new.action)
    # When approved, the paused workflow follows the switch and runs the new proposal, after
    # this request commits (hard rule 5).
    if result.approval is not None:
        background.add_task(_after_decision, engine, ctx, new.case_id, new.id, new.action, True)
    return SwitchOut(
        old_proposal_id=result.old_proposal_id,
        proposal_id=new.id,
        action=new.action,
        amount_paise=new.amount_paise,
        decision=result.approval.decision if result.approval else None,
        waiting_for=result.waiting_for,
        self_approved=result.self_approved,
        expires_at=result.approval.expires_at if result.approval else None,
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
