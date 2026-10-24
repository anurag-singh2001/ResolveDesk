import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db_engine, get_tenant_context, not_found, require_staff, tenant_db
from app.api.routes_approvals import run_refund
from app.config import get_settings
from app.core.models import ActionProposal, Approval, AuditEvent, Case, Customer, Transaction
from app.core.tenancy import TenantContext
from app.engine.agent_runner import run_agents
from app.engine.case_status import case_status
from app.engine.cases import CaseNotFound, InvalidCategory, open_case

router = APIRouter(tags=["cases"])


class CaseIn(BaseModel):
    transaction_id: uuid.UUID
    # Required in deterministic mode; optional in agents mode (the classifier decides).
    category: str | None = None
    message: str = Field(min_length=1, max_length=2000)


class CaseOut(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID | None
    category: str | None
    stage: str
    message: str
    action: str | None = None
    amount_paise: int | None = None
    proposal_id: str | None = None


def _out(db: Session, case: Case) -> CaseOut:
    st = case_status(db, case)
    return CaseOut(
        id=case.id,
        transaction_id=case.transaction_id,
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
            now=datetime.now(UTC),
        )
    except CaseNotFound:
        raise not_found() from None
    except InvalidCategory as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    db.flush()
    if body.category is None and case.status == "investigating":
        background.add_task(run_agents, engine, ctx.tenant_id, case.id, body.message)
    if proposal_id is not None:  # an auto-approved refund must actually run
        proposal = db.get(ActionProposal, proposal_id)
        approved = db.scalar(select(Approval.id).where(Approval.proposal_id == proposal_id))
        if proposal.action == "refund" and approved is not None:
            background.add_task(run_refund, engine, ctx, proposal_id)
    return _out(db, case)


@router.get("/cases")
def list_cases(
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> list[CaseOut]:
    """Customers: their own cases. hq_owner: all. Scoped staff: cases on orders in scope."""
    query = select(Case).order_by(Case.opened_at.desc(), Case.id).limit(limit)
    if ctx.role == "customer":
        own = select(Customer.id).where(Customer.user_id == ctx.user_id)
        query = query.where(Case.customer_id.in_(own))
    elif ctx.role != "hq_owner":
        visible = select(Transaction.id).where(ctx.visible_orders())
        query = query.where(Case.transaction_id.in_(visible))
    return [_out(db, case) for case in db.scalars(query)]


@router.get("/cases/{case_id}")
def get_case(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> CaseOut:
    return _out(db, visible_case(db, ctx, case_id))


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
