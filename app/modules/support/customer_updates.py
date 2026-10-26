"""Subscriber: keeps the case's ticket in step with the case (customer update + ticket status).

The message is the code-templated text from case_status, computed from what the database
says at that moment, so it never claims more than a tool confirmed (hard rule 7); no model
writes customer text. Idempotent: the same text twice in a row is posted once, so a
re-delivered event (events.publish_pending) adds nothing.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import subscribe
from app.core.models import Case, DomainEvent, Ticket, TicketMessage
from app.engine.case_status import case_status

# case status -> ticket status
TICKET_STATUS = {"resolved": "resolved", "escalated": "escalated", "closed": "closed"}


@subscribe(
    "case.proposed",
    "case.approved",
    "case.rejected",
    "case.executed",
    "case.verified",
    "case.escalated",
)
def post_customer_update(session: Session, event: DomainEvent) -> None:
    case = session.get(Case, event.entity_id) if event.entity_id else None
    if case is None:
        return
    ticket = session.scalar(select(Ticket).where(Ticket.case_id == case.id))
    if ticket is None:
        return
    now = datetime.now(UTC)
    ticket_status = TICKET_STATUS.get(case.status, "open")
    if ticket.status != ticket_status:
        ticket.status = ticket_status
        ticket.closed_at = now if ticket_status in ("resolved", "closed") else None
    body = case_status(session, case, now).message
    last = session.scalars(
        select(TicketMessage.body)
        .where(TicketMessage.ticket_id == ticket.id, TicketMessage.author == "system")
        .order_by(TicketMessage.sent_at.desc(), TicketMessage.created_at.desc())
        .limit(1)
    ).first()
    if last != body:
        session.add(TicketMessage(tenant_id=case.tenant_id, ticket_id=ticket.id,
                                  author="system", body=body, sent_at=now))  # fmt: skip
