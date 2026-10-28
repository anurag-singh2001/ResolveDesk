import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_clock,
    get_db_engine,
    get_tenant_context,
    not_found,
    require_staff,
    tenant_db,
)
from app.api.routes_approvals import run_execution
from app.config import get_settings
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Customer,
    Location,
    Transaction,
    User,
)
from app.core.tenancy import TenantContext
from app.engine.agent_runner import resume_info, run_agents
from app.engine.case_messages import customer_messages
from app.engine.case_status import case_status
from app.engine.case_timeline import case_timeline
from app.engine.cases import CaseNotFound, InvalidCategory, NotAwaitingInfo, add_reply, open_case
from app.engine.dispatch import executable
from app.engine.routing import (
    NEEDS_PERSON_STATUSES,
    REASON_LABELS,
    NotAllowed,
    NotAssignable,
    NotNeedingPerson,
    reason_code,
    reassign,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["cases"])


class CaseIn(BaseModel):
    transaction_id: uuid.UUID
    # Required in deterministic mode; optional in agents mode (the classifier decides).
    category: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class CustomerMessageOut(BaseModel):
    at: datetime
    text: str


class CaseOut(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID | None
    order_ref: str | None
    category: str | None
    stage: str
    message: str
    action: str | None = None
    amount_paise: int | None = None
    proposal_id: str | None = None
    created_at: datetime


class CaseDetailOut(CaseOut):
    # The customer's own words, oldest first. Only on GET /cases/{id}, after visible_case
    # (the owning customer or staff who can see the order); list responses omit the field.
    customer_messages: list[CustomerMessageOut] = []


def _out(db: Session, case: Case, now: datetime) -> CaseOut:
    st = case_status(db, case, now)
    order = db.get(Transaction, case.transaction_id) if case.transaction_id else None
    return CaseOut(
        id=case.id,
        transaction_id=case.transaction_id,
        order_ref=order.external_ref if order else None,
        created_at=case.opened_at,
        category=case.category,
        stage=st.stage,
        message=st.message,
        action=st.action,
        amount_paise=st.amount_paise,
        proposal_id=st.proposal_id,
    )


def visible_case(db: Session, ctx: TenantContext, case_id: uuid.UUID) -> Case:
    """The case if the caller may see it, else 404 (also for other tenants: RLS)."""
    case = db.get(Case, case_id)
    if case is None:
        raise not_found()
    if ctx.role == "customer":
        owner = db.scalar(select(Customer.user_id).where(Customer.id == case.customer_id))
        if owner != ctx.user_id:
            raise not_found()
        return case
    if ctx.role == "hq_owner":
        return case
    if (
        case.transaction_id is None
        or db.scalar(
            select(Transaction.id).where(
                Transaction.id == case.transaction_id, ctx.visible_orders()
            )
        )
        is None
    ):
        raise not_found()
    return case


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def create_case(
    body: CaseIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> CaseOut:
    if ctx.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customers open cases")
    agents = get_settings().engine_mode == "agents"
    if body.category is None and not agents:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "category is required")
    try:
        case, proposal_id = open_case(
            db,
            ctx,
            transaction_id=body.transaction_id,
            category=body.category,
            message=body.message,
            now=datetime.now(UTC),  # a write: real time, never the dev clock
        )
    except CaseNotFound:
        raise not_found() from None
    except InvalidCategory as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    db.flush()
    if body.category is None and case.status == "investigating":
        background.add_task(run_agents, engine, ctx.tenant_id, case.id, body.message)
    elif case.status == "awaiting_info":  # a reply on a case waiting for it: resume its thread
        background.add_task(resume_info, engine, ctx.tenant_id, case.id, body.message)
    if proposal_id is not None:  # an auto-approved remedy must actually run
        proposal = db.get(ActionProposal, proposal_id)
        approved = db.scalar(select(Approval.id).where(Approval.proposal_id == proposal_id))
        if approved is not None and executable(proposal.action):
            background.add_task(run_execution, engine, ctx, proposal_id, proposal.action)
    return _out(db, case, datetime.now(UTC))


def _resume_after_reply(
    engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, message: str
) -> None:
    """Background task for a reply. The reply is already stored; if the graph did not pick
    it up, say so (the sweeper re-drives it or escalates the case)."""
    out = resume_info(engine, tenant_id, case_id, message)
    if out.get("outcome") == "skipped":
        log.warning(
            "reply on case %s did not resume the workflow (%s); the sweeper will retry",
            case_id,
            out.get("reason"),
        )


class ReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/cases/{case_id}/messages", status_code=status.HTTP_201_CREATED)
def add_case_message(
    case_id: uuid.UUID,
    body: ReplyIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> CaseOut:
    """The customer answers a needs-info question on their own case; the case then continues."""
    if ctx.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customers reply on their cases")
    case = visible_case(db, ctx, case_id)  # someone else's / another tenant's case: 404
    now = datetime.now(UTC)  # a write: real time, never the dev clock
    try:
        add_reply(db, ctx, case, body.message, now)
    except NotAwaitingInfo as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.flush()
    if get_settings().engine_mode == "agents":  # the graph re-reads the whole conversation
        background.add_task(_resume_after_reply, engine, ctx.tenant_id, case.id, body.message)
    return _out(db, case, now)


@router.get("/cases")
def list_cases(
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> list[CaseOut]:
    """Customers: their own cases. hq_owner: all. Scoped staff: cases on orders in scope."""
    query = select(Case).order_by(Case.opened_at.desc(), Case.id).limit(limit)
    if ctx.role == "customer":
        own = select(Customer.id).where(Customer.user_id == ctx.user_id)
        query = query.where(Case.customer_id.in_(own))
    elif ctx.role != "hq_owner":
        visible = select(Transaction.id).where(ctx.visible_orders())
        query = query.where(Case.transaction_id.in_(visible))
    return [_out(db, case, now) for case in db.scalars(query)]


class QueueItemOut(BaseModel):
    case_id: uuid.UUID
    order_ref: str | None
    location_name: str | None
    category: str | None
    status: str
    reason_kind: Literal["escalated", "awaiting_approval"]
    reason_code: str
    reason: str  # the fixed label for reason_code, never stored or customer text
    waiting_since: datetime
    waiting_seconds: int
    owner_user_id: uuid.UUID | None
    owner_name: str | None
    owned_by_me: bool
    language: str
    amount_paise: int | None = None
    proposal_id: uuid.UUID | None = None


@router.get("/cases/queue")
def cases_to_handle(
    reason: Literal["escalated", "awaiting_approval"] | None = None,
    category: str | None = Query(None, max_length=64),
    owned_by_me: bool = False,
    limit: int = Query(100, ge=1, le=200),
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> list[QueueItemOut]:
    """Cases that need a person, in the caller's scope (manager: own outlets; franchisee:
    theirs; HQ: all), oldest wait first. Scope reuses the orders scope, so an out-of-scope or
    other-tenant case is simply absent."""
    wanted = (reason,) if reason else NEEDS_PERSON_STATUSES
    query = (
        select(Case, Transaction.external_ref, Location.name)
        .outerjoin(Transaction, Transaction.id == Case.transaction_id)
        .outerjoin(Location, Location.id == Transaction.location_id)
        .where(Case.status.in_(wanted))
    )
    if ctx.role != "hq_owner":
        query = query.where(and_(Transaction.id.is_not(None), ctx.visible_orders()))
    if category is not None:
        query = query.where(Case.category == category)
    if owned_by_me:
        query = query.where(Case.owner_user_id == ctx.user_id)
    rows = db.execute(query).all()
    ids = [c.id for c, _, _ in rows]
    escalated_at: dict[uuid.UUID, tuple[datetime, str, str]] = {}
    for ev in db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.entity_id.in_(ids), AuditEvent.event.in_(("case.escalated", "case.escalate"))
        )
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
    ):
        escalated_at[ev.entity_id] = (
            ev.occurred_at,
            ev.event,
            str(ev.payload.get("reason") or ""),
        )
    approved_cases = set(
        db.scalars(
            select(ActionProposal.case_id)
            .join(Approval, Approval.proposal_id == ActionProposal.id)
            .where(ActionProposal.case_id.in_(ids))
        )
    )
    pending: dict[uuid.UUID, ActionProposal] = {}
    for proposal in db.scalars(
        select(ActionProposal)
        .outerjoin(Approval, Approval.proposal_id == ActionProposal.id)
        .where(ActionProposal.case_id.in_(ids), Approval.id.is_(None))
        .order_by(ActionProposal.created_at, ActionProposal.id)
    ):
        pending[proposal.case_id] = proposal
    owner_ids = {c.owner_user_id for c, _, _ in rows if c.owner_user_id}
    # An erased user's account is dead (DPDP): never show their name on a case.
    names = {
        uid: name if erased is None else "Former staff member"
        for uid, name, erased in db.execute(
            select(User.id, User.display_name, User.erased_at).where(User.id.in_(owner_ids))
        ).all()
    }
    langs = dict(
        db.execute(
            select(Customer.id, Customer.preferred_language).where(
                Customer.id.in_({c.customer_id for c, _, _ in rows})
            )
        ).all()
    )
    items = []
    for case, order_ref, location_name in rows:
        kind = "awaiting_approval" if case.status == "awaiting_approval" else "escalated"
        proposal = pending.get(case.id)
        if kind == "awaiting_approval":
            since = proposal.created_at if proposal else case.opened_at
            code = reason_code(case.status, case.category, None, "", False)
        else:
            since, event, raw = escalated_at.get(case.id, (case.opened_at, None, ""))
            code = reason_code(case.status, case.category, event, raw, case.id in approved_cases)
        items.append(
            QueueItemOut(
                case_id=case.id,
                order_ref=order_ref,
                location_name=location_name,
                category=case.category,
                status=case.status,
                reason_kind=kind,
                reason_code=code,
                reason=REASON_LABELS[code],
                waiting_since=since,
                waiting_seconds=max(0, int((now - since).total_seconds())),
                owner_user_id=case.owner_user_id,
                owner_name=names.get(case.owner_user_id),
                owned_by_me=case.owner_user_id == ctx.user_id,
                language=langs.get(case.customer_id) or "en",
                amount_paise=proposal.amount_paise if proposal else None,
                proposal_id=proposal.id if proposal else None,
            )
        )
    items.sort(key=lambda i: (i.waiting_since, str(i.case_id)))
    return items[:limit]


class OwnerIn(BaseModel):
    user_id: uuid.UUID


class OwnerOut(BaseModel):
    case_id: uuid.UUID
    owner_user_id: uuid.UUID


@router.post("/cases/{case_id}/owner")
def set_case_owner(
    case_id: uuid.UUID,
    body: OwnerIn,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> OwnerOut:
    """Hand a case that needs a person to another staff member who can see its outlet.
    Franchisee owners (their outlets) and HQ only; a case out of scope is a 404 first.
    This changes who is responsible, never who may approve (approvals.decide)."""
    case = visible_case(db, ctx, case_id)
    try:
        reassign(db, ctx, case, body.user_id, datetime.now(UTC))
    except NotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except NotNeedingPerson as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except NotAssignable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return OwnerOut(case_id=case.id, owner_user_id=body.user_id)


@router.get("/cases/{case_id}")
def get_case(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> CaseDetailOut:
    case = visible_case(db, ctx, case_id)
    return CaseDetailOut(
        **_out(db, case, now).model_dump(),
        customer_messages=[
            CustomerMessageOut(at=at, text=text) for at, text in customer_messages(db, case.id)
        ],
    )


class TimelineStepOut(BaseModel):
    at: datetime
    stage: str
    title: str
    text: str


@router.get("/cases/{case_id}/timeline")
def get_case_timeline(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> list[TimelineStepOut]:
    """Customer-safe steps, oldest first; same visibility as GET /cases/{id}."""
    case = visible_case(db, ctx, case_id)
    return [
        TimelineStepOut(at=s.at, stage=s.stage, title=s.title, text=s.text)
        for s in case_timeline(db, case, now)
    ]


class EventOut(BaseModel):
    occurred_at: datetime
    actor_type: str
    event: str
    payload: dict


@router.get("/cases/{case_id}/events")
def case_events(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> list[EventOut]:
    """Redacted timeline for staff (payloads were redacted when written)."""
    case = visible_case(db, ctx, case_id)
    proposal_ids = select(ActionProposal.id).where(ActionProposal.case_id == case.id)
    rows = db.scalars(
        select(AuditEvent)
        .where(or_(AuditEvent.entity_id == case.id, AuditEvent.entity_id.in_(proposal_ids)))
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
    )
    return [
        EventOut(
            occurred_at=r.occurred_at, actor_type=r.actor_type, event=r.event, payload=r.payload
        )
        for r in rows
    ]
