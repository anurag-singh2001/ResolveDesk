"""What the customer actually wrote on a case (the words, not our template status text)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Ticket, TicketMessage


def customer_messages(db: Session, case_id: uuid.UUID) -> list[tuple[datetime, str]]:
    """All customer-authored messages on the case, oldest first (first report, then replies).
    Callers must already have checked the viewer may see the case."""
    rows = db.execute(
        select(TicketMessage.sent_at, TicketMessage.body)
        .join(Ticket, Ticket.id == TicketMessage.ticket_id)
        .where(Ticket.case_id == case_id, TicketMessage.author == "customer")
        .order_by(TicketMessage.sent_at, TicketMessage.id)
    )
    return [(r[0], r[1]) for r in rows]


def first_customer_message(db: Session, case_id: uuid.UUID) -> str | None:
    msgs = customer_messages(db, case_id)
    return msgs[0][1] if msgs else None


def staff_messages(db: Session, case_id: uuid.UUID) -> list[TicketMessage]:
    """What staff sent the customer on the case (S7.6), oldest first. Staff view only."""
    return list(
        db.scalars(
            select(TicketMessage)
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .where(Ticket.case_id == case_id, TicketMessage.author == "staff")
            .order_by(TicketMessage.sent_at, TicketMessage.id)
        )
    )
