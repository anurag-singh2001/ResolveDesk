"""What we may need from a customer, and the question code sends for it (hard rule 7).

The graph records only a need *code* (never model text) on the case.awaiting_info audit event;
the customer-facing status and timeline turn that code into one of these templates. An unknown
or missing code (an older event, a future code) gets the generic sentence, never free text.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AuditEvent

NEED_ORDER = "order"
NEED_DETAILS = "details"
QUESTIONS = {
    NEED_ORDER: "Which order is this about? Please pick it from your order list.",
    NEED_DETAILS: "So we can look into it, could you tell us a bit more about what went wrong"
    " with your order (for example, which item was affected)?",
}
GENERIC_QUESTION = "Could you tell us a bit more about what went wrong with this order?"


def question_for(code: object) -> str:
    return QUESTIONS.get(code, GENERIC_QUESTION) if isinstance(code, str) else GENERIC_QUESTION


def need_from_payload(payload: object) -> str | None:
    code = payload.get("need") if isinstance(payload, dict) else None
    return code if isinstance(code, str) else None


def latest_question(session: Session, case_id: uuid.UUID) -> str:
    """The question of the case's most recent case.awaiting_info event."""
    payload = session.scalar(
        select(AuditEvent.payload)
        .where(
            AuditEvent.entity_type == "case",
            AuditEvent.entity_id == case_id,
            AuditEvent.event == "case.awaiting_info",
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    return question_for(need_from_payload(payload))
