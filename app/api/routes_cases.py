import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, StrictInt
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
from app.core.i18n import case_language
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
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.engine import ai_rerun, staff_decisions
from app.engine.agent_runner import resume_info, run_agents
from app.engine.approvals import not_superseded
from app.engine.case_messages import customer_messages, staff_messages
from app.engine.case_status import case_status
from app.engine.case_timeline import case_timeline
from app.engine.cases import CaseNotFound, InvalidCategory, NotAwaitingInfo, add_reply, open_case
from app.engine.dispatch import executable
from app.engine.remedy_choice import (
    ChoiceClosed,
    InvalidChoice,
    customer_language,
    options_for_order,
    set_choice,
)
from app.engine.routing import (
    NEEDS_PERSON_STATUSES,
    REASON_LABELS,
    NotAllowed,
    NotAssignable,
    NotNeedingPerson,
    reason_code,
    reassign,
)
from app.engine.staff_actions import (
    CLOSE_REASONS,
    NOTE_MAX_LENGTH,
    CaseClosed,
    PayoutInFlight,
    ReplayMismatch,
    StaffActionError,
    available_templates,
    close_case,
    send_reply,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["cases"])


class CaseIn(BaseModel):
    transaction_id: uuid.UUID
    # Required in deterministic mode; optional in agents mode (the classifier decides).
    category: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    # One of the option codes offered for this order and category (S7.9); optional.
    remedy_choice: str | None = Field(default=None, max_length=32)


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


class StaffMessageOut(BaseModel):
    at: datetime
    kind: str  # template | note
    template_id: str | None
    text: str
    sender_user_id: uuid.UUID | None


class CaseDetailOut(CaseOut):
    # The customer's own words, oldest first. Only on GET /cases/{id}, after visible_case
    # (the owning customer or staff who can see the order); list responses omit the field.
    customer_messages: list[CustomerMessageOut] = []
    # Staff only: the case escalated for an AI failure, so "Run the AI again" applies (S7.4).
    can_rerun_ai: bool = False
    # Staff only (empty for customers, who see these in the timeline): what staff sent, and the
    # close reason once closed (S7.6).
    staff_messages: list["StaffMessageOut"] = []
    closed: bool = False
    close_reason: str | None = None


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
            remedy_choice=body.remedy_choice,
        )
    except CaseNotFound:
        raise not_found() from None
    except InvalidChoice as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
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


class RemedyOptionOut(BaseModel):
    code: str
    kind: str
    title: str
    summary: str
    amount_paise: int
    approval: str  # instant | team
    timing: str


class RemedyOptionsOut(BaseModel):
    options: list[RemedyOptionOut]
    choice_required: bool  # False: zero or one option, so the customer has nothing to pick


class RemedyChoiceIn(BaseModel):
    option: str = Field(min_length=1, max_length=32)


def _visible_order(db: Session, ctx: TenantContext, order_id: uuid.UUID) -> Transaction:
    """The order if the caller may see it (their own, for a customer), else 404."""
    order = db.scalar(select(Transaction).where(Transaction.id == order_id, ctx.visible_orders()))
    if order is None:
        raise not_found()
    return order


def _options_out(db: Session, ctx: TenantContext, order: Transaction, category: str, now: datetime):
    options = options_for_order(db, order, category, customer_language(db, ctx), now)
    return RemedyOptionsOut(options=options, choice_required=len(options) > 1)


@router.get("/orders/{order_id}/remedy-options")
def order_remedy_options(
    order_id: uuid.UUID,
    category: str = Query(min_length=1, max_length=64),
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> RemedyOptionsOut:
    """What a customer may choose for this category on their own order. Another customer's or
    tenant's order is a 404; the amounts are computed here, never taken from the client."""
    if ctx.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customers only")
    if category not in tenant_pack(db).issue_categories:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown category")
    return _options_out(db, ctx, _visible_order(db, ctx, order_id), category, now)


@router.get("/cases/{case_id}/remedy-options")
def case_remedy_options(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> RemedyOptionsOut:
    """The same options for a case that is still undecided; empty once a proposal exists."""
    if ctx.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customers only")
    case = visible_case(db, ctx, case_id)
    has_proposal = db.scalar(select(ActionProposal.id).where(ActionProposal.case_id == case.id))
    if (
        case.status not in ("investigating", "awaiting_info")
        or has_proposal is not None
        or case.category is None
        or case.transaction_id is None
    ):
        return RemedyOptionsOut(options=[], choice_required=False)
    return _options_out(db, ctx, _visible_order(db, ctx, case.transaction_id), case.category, now)


@router.put("/cases/{case_id}/remedy-choice")
def put_remedy_choice(
    case_id: uuid.UUID,
    body: RemedyChoiceIn,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> CaseOut:
    if ctx.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customers only")
    case = visible_case(db, ctx, case_id)  # someone else's / another tenant's case: 404
    try:
        set_choice(db, ctx, case.id, body.option)
    except ChoiceClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except InvalidChoice as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
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
        .where(ActionProposal.case_id.in_(ids), Approval.id.is_(None), not_superseded())
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
    staff_msgs = (
        []
        if ctx.role == "customer"
        else [
            StaffMessageOut(
                at=m.sent_at,
                kind=m.kind or "template",
                template_id=m.template_id,
                text=m.body,
                sender_user_id=m.sender_user_id,
            )
            for m in staff_messages(db, case.id)
        ]
    )
    return CaseDetailOut(
        **_out(db, case, now).model_dump(),
        customer_messages=[
            CustomerMessageOut(at=at, text=text) for at, text in customer_messages(db, case.id)
        ],
        can_rerun_ai=ctx.is_staff and ai_rerun.can_rerun(db, case),
        staff_messages=staff_msgs,
        closed=case.status == "closed",
        close_reason=case.close_reason,
    )


class TemplateOut(BaseModel):
    id: str
    label: str
    preview: str  # the text as the customer will read it, in the case language


class CloseReasonOut(BaseModel):
    id: str
    label: str


class ReplyTemplatesOut(BaseModel):
    language: str
    templates: list[TemplateOut]
    close_reasons: list[CloseReasonOut]
    note_max_length: int
    closed: bool


@router.get("/cases/{case_id}/reply-templates")
def reply_templates(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> ReplyTemplatesOut:
    """The replies staff may send on this case, previewed in the case language. A template
    that would state a fact the case does not have (a refund being processed) is absent."""
    case = visible_case(db, ctx, case_id)
    return ReplyTemplatesOut(
        language=case_language(db, case),
        templates=[
            TemplateOut(id=o.id, label=o.label, preview=o.preview)
            for o in available_templates(db, case, now)
        ],
        close_reasons=[CloseReasonOut(id=k, label=v) for k, v in CLOSE_REASONS.items()],
        note_max_length=NOTE_MAX_LENGTH,
        closed=case.status == "closed",
    )


class StaffReplyIn(BaseModel):
    template_id: str = Field(min_length=1, max_length=48)
    note: str | None = Field(default=None, max_length=1000)
    # One per form submit; a double click or retry with the same key stores one message.
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)


class StaffReplyOut(BaseModel):
    sent: bool  # False: this submit was already stored


def _staff_error(exc: StaffActionError) -> HTTPException:
    if isinstance(exc, (CaseClosed, PayoutInFlight, ReplayMismatch)):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.post("/cases/{case_id}/staff-reply")
def staff_reply(
    case_id: uuid.UUID,
    body: StaffReplyIn,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    clock: datetime = Depends(get_clock),
) -> StaffReplyOut:
    case = visible_case(db, ctx, case_id)  # out of scope / other tenant: 404
    try:
        sent = send_reply(
            db,
            ctx,
            case,
            template_id=body.template_id,
            note=body.note,
            idempotency_key=body.idempotency_key,
            now=datetime.now(UTC),  # a write: real time, never the dev clock
            clock=clock,  # status checks use the same clock as the template list
        )
    except StaffActionError as exc:
        raise _staff_error(exc) from None
    return StaffReplyOut(sent=sent)


class CloseIn(BaseModel):
    reason: str = Field(min_length=1, max_length=24)


class CloseOut(BaseModel):
    case_id: uuid.UUID
    status: str
    close_reason: str


@router.post("/cases/{case_id}/close")
def close(
    case_id: uuid.UUID,
    body: CloseIn,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> CloseOut:
    """Close a case with a reason. 409 if already closed or a remedy is still undecided or
    unfinished (closing must not strand a payout)."""
    case = visible_case(db, ctx, case_id)
    try:
        close_case(db, ctx, case, reason=body.reason, now=datetime.now(UTC))
    except StaffActionError as exc:
        raise _staff_error(exc) from None
    return CloseOut(case_id=case.id, status=case.status, close_reason=body.reason)


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


class RerunOut(BaseModel):
    status: str  # "started" | "already_running"


@router.post("/cases/{case_id}/rerun-ai", status_code=status.HTTP_202_ACCEPTED)
def rerun_ai(
    case_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
) -> RerunOut:
    """Staff re-run the AI on a case that escalated because the AI was unavailable. The case
    is claimed under a row lock (a double click starts one run); the run itself is a
    background task, after this request is done, so no model call happens in a transaction."""
    case = visible_case(db, ctx, case_id)  # out of scope / other tenant: 404
    outcome = ai_rerun.request_rerun(
        engine, ctx.tenant_id, case.id, trigger="staff", actor_id=ctx.user_id
    )
    if outcome == ai_rerun.NOT_ELIGIBLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "the case did not escalate for an AI failure")
    if outcome == ai_rerun.STARTED:
        background.add_task(ai_rerun.run_requested, engine, ctx.tenant_id, case.id, "staff")
    return RerunOut(status=outcome)


class RemedyOptionOut(BaseModel):
    action: str
    min_paise: int
    max_paise: int


class RemedyOptionsOut(BaseModel):
    categories: list[str]
    category: str | None
    options: list[RemedyOptionOut]
    note: str | None


def _staff_case_needing_person(db: Session, ctx: TenantContext, case_id: uuid.UUID) -> Case:
    """Scope first (404 for out-of-scope and other-tenant cases), then 409 when the case is
    not waiting for a person. Customers never get here (require_staff: 403)."""
    case = visible_case(db, ctx, case_id)
    try:
        staff_decisions.require_person_needed(db, case)
    except staff_decisions.NotNeedingPerson as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return case


@router.get("/cases/{case_id}/staff-remedy-options")
def get_remedy_options(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> RemedyOptionsOut:
    """The category list and the remedies the vertical pack's rules allow for this case now,
    with the amount range in paise. Staff in scope only, on a case that needs a person."""
    case = _staff_case_needing_person(db, ctx, case_id)
    found = staff_decisions.remedy_options(db, case)
    return RemedyOptionsOut(
        categories=found.categories,
        category=found.category,
        options=[RemedyOptionOut(**vars(o)) for o in found.options],
        note=found.note,
    )


class CategoriseIn(BaseModel):
    category: str = Field(min_length=1, max_length=64)


@router.post("/cases/{case_id}/categorise")
def categorise_case(
    case_id: uuid.UUID,
    body: CategoriseIn,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> RemedyOptionsOut:
    case = _staff_case_needing_person(db, ctx, case_id)
    try:
        case = staff_decisions.categorise(db, ctx, case, body.category, datetime.now(UTC))
    except staff_decisions.NotNeedingPerson as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except staff_decisions.InvalidChoice as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return get_remedy_options(case_id, ctx, db)


class ProposeIn(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    amount_paise: StrictInt | None = None  # integer paise; a client value is only a proposal


class ProposedOut(BaseModel):
    proposal_id: uuid.UUID
    case_id: uuid.UUID
    action: str
    amount_paise: int | None
    created: bool
    status: Literal["awaiting_approval", "approved", "executed", "rejected", "expired"]
    needs_hq: bool


@router.post("/cases/{case_id}/propose")
def propose_remedy(
    case_id: uuid.UUID,
    body: ProposeIn,
    response: Response,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> ProposedOut:
    """Staff pick a remedy for a case that needs a person. It becomes an ordinary proposal
    (same checks, same approval, same executor as the AI's); nothing is paid here."""
    case = visible_case(db, ctx, case_id)  # 404 first; a repeat of an earlier request is fine
    try:
        out = staff_decisions.propose(
            db, ctx, case, action=body.action, amount_paise=body.amount_paise, now=datetime.now(UTC)
        )
    except staff_decisions.NotNeedingPerson as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except staff_decisions.InvalidChoice as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    proposal = out.proposal  # a person proposed it, so it always waits for another person
    response.status_code = status.HTTP_201_CREATED if out.created else status.HTTP_200_OK
    return ProposedOut(
        proposal_id=proposal.id,
        case_id=case.id,
        action=proposal.action,
        amount_paise=proposal.amount_paise,
        created=out.created,
        status=out.state,
        needs_hq=bool(out.checks.get("needs_hq")),
    )
