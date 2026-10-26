"""Case lifecycle for the no-LLM path: open -> propose -> (auto)approve -> execute -> verify."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.models import Case, Customer, Ticket, TicketMessage, Transaction
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.engine import lifecycle
from app.engine.resolver import propose_for_case

OPEN_STATUSES = ("open", "investigating", "awaiting_info", "awaiting_approval", "executing")


UNCLASSIFIED = "unknown"  # ticket category until the agent pipeline classifies the case


class CaseError(Exception):
    code = "case_error"


class CaseNotFound(CaseError):
    code = "not_found"


class InvalidCategory(CaseError):
    code = "invalid_category"


class NotAwaitingInfo(CaseError):
    code = "not_awaiting_info"


def open_case(
    session: Session,
    ctx: TenantContext,
    *,
    transaction_id: uuid.UUID,
    category: str | None,
    message: str,
    now: datetime,
) -> tuple[Case, uuid.UUID | None]:
    """A customer opens a case on one of THEIR orders. Returns (case, proposal id or None).

    The order id comes from the request, so ownership is checked server-side through the
    caller's own customer record (hard rule 8): anything else looks like "not found".
    """
    if ctx.role != "customer":
        raise CaseNotFound("only customers open cases")
    if category is not None and category not in tenant_pack(session).issue_categories:
        raise InvalidCategory(f"unknown category {category!r}")
    # Lock the order row: two simultaneous reports can't both open a case for it.
    order = session.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id, ctx.visible_orders())
        .with_for_update()
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
        ticket_id = session.scalar(select(Ticket.id).where(Ticket.case_id == existing.id))
        if ticket_id is not None:  # keep what the customer said, on the same thread
            session.add(
                TicketMessage(
                    tenant_id=ctx.tenant_id,
                    ticket_id=ticket_id,
                    author="customer",
                    body=message,
                    sent_at=now,
                )
            )
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
        category=category or UNCLASSIFIED,  # the classifier sets it (agents mode)
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
    events.emit(session, ctx.tenant_id, "case.opened", case.id, {"category": category})

    if category is None:  # free text: the agent pipeline classifies and proposes (graph)
        return case, None
    remedy, proposal_id = propose_for_case(session, ctx, case)
    if proposal_id is None:
        case.status = "escalated" if remedy.outcome == "escalate" else "resolved"
        if case.status == "escalated":
            events.emit(session, ctx.tenant_id, "case.escalated", case.id,
                        {"reason": remedy.reason[:200]})  # fmt: skip
    else:
        lifecycle.proposal_made(session, ctx.tenant_id, case, proposal_id, now)
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


def add_reply(
    session: Session, ctx: TenantContext, case: Case, message: str, now: datetime
) -> None:
    """The customer answers the question a case is waiting on: keep their words on the case's
    ticket (the graph re-reads the whole conversation when it resumes) and note it in the audit
    trail. The caller has already checked the case is theirs. The row lock makes the status check
    race-free; the graph's own resume claim makes a double submit continue the thread once."""
    locked = session.scalar(select(Case).where(Case.id == case.id).with_for_update())
    if locked is None or locked.status != "awaiting_info":
        raise NotAwaitingInfo("this case is not waiting for more information")
    ticket_id = session.scalar(select(Ticket.id).where(Ticket.case_id == case.id))
    if ticket_id is None:
        raise NotAwaitingInfo("this case has no conversation to add to")
    session.add(
        TicketMessage(
            tenant_id=ctx.tenant_id,
            ticket_id=ticket_id,
            author="customer",
            body=message,
            sent_at=now,
        )
    )
    # No message text in the audit payload: the words live on the ticket only.
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.info_added",
        entity_type="case",
        entity_id=case.id,
        payload={},
    )
