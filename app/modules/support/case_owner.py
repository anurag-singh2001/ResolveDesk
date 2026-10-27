"""Subscriber: a case that starts needing a person gets its owner (S7.2, app/engine/routing.py)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.events import subscribe
from app.core.models import Case, DomainEvent
from app.engine.routing import assign_owner


@subscribe("case.escalated", "case.proposed")
def assign_case_owner(session: Session, event: DomainEvent) -> None:
    case = session.get(Case, event.entity_id) if event.entity_id else None
    if case is not None:
        # assign_owner ignores statuses that need nobody (e.g. an auto-approved proposal).
        assign_owner(session, event.tenant_id, case, datetime.now(UTC))
