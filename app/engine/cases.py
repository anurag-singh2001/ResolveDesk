"""Case lifecycle for the no-LLM path: open -> propose -> (auto)approve -> execute."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import Case, Customer, Ticket, TicketMessage, Transaction
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.engine.approvals import auto_decide
from app.engine.resolver import propose_for_case

OPEN_STATUSES = ("open", "investigating", "awaiting_info", "awaiting_approval", "executing")


class CaseError(Exception):
    code = "case_error"


class CaseNotFound(CaseError):
    code = "not_found"


class InvalidCategory(CaseError):
    code = "invalid_category"


def open_case(
    session: Session,
    ctx: TenantContext,
    *,
    transaction_id: uuid.UUID,
    category: str,
    message: str,
    now: datetime,
) -> tuple[Case, uuid.UUID | None]:
    """A customer opens a case on one of THEIR orders. Returns (case, proposal id or None).

    The order id comes from the request, so ownership is checked server-side through the
    caller's own customer record (hard rule 8): anything else looks like "not found".
    """
    if ctx.role != "customer":
        raise CaseNotFound("only customers open cases")
    if category not in tenant_pack(session).issue_categories:
        raise InvalidCategory(f"unknown category {category!r}")
    order = session.scalar(
        select(Transaction).where(Transaction.id == transaction_id, ctx.visible_orders())
    )
    if order is None:
        raise CaseNotFound("order not found")
    customer = session.scalar(select(Customer).where(Customer.user_id == ctx.user_id))
    existing = session.scalar(
        select(Case).where(
            Case.customer_id == customer.id,
            Case.transaction_id == order.id,
            Case.status.in_(OPEN_STATUSES),
        )
    )
    if existing is not None:  # a retry or a second report: same case, no new proposal
        return existing, None

    case = Case(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        customer_id=customer.id,
        transaction_id=order.id,
        category=category,
        status="investigating",
        channel="app",
        opened_at=now,
    )
    session.add(case)
    session.flush()
    ticket = Ticket(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        customer_id=customer.id,
        transaction_id=order.id,
        case_id=case.id,
        category=category,
        status="open",
        channel="app",
        opened_at=now,
    )
    session.add(ticket)
    session.flush()
    session.add(
        TicketMessage(
            tenant_id=ctx.tenant_id,
            ticket_id=ticket.id,
            author="customer",
            body=message,
            sent_at=now,
        )
    )
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.opened",
        entity_type="case",
        entity_id=case.id,
        payload={"category": category, "message": message},
    )

    remedy, proposal_id = propose_for_case(session, ctx, case)
    if proposal_id is None:
        case.status = "escalated" if remedy.outcome == "escalate" else "resolved"
    else:
        approval = auto_decide(session, ctx.tenant_id, proposal_id, now)
        case.status = "executing" if approval is not None else "awaiting_approval"
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="system",
        actor_id=None,
        event=f"case.{remedy.outcome}",
        entity_type="case",
        entity_id=case.id,
        payload={"reason": remedy.reason, "proposal_id": str(proposal_id or "")},
    )
    return case, proposal_id
