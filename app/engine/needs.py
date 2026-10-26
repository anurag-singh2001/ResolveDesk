"""What we may need from a customer, and the question code sends for it (hard rule 7).

The graph records only a need *code* (never model text) on the case.awaiting_info audit event;
the customer-facing status and timeline turn that code into one of these templates. An unknown
or missing code (an older event, a future code) gets the generic sentence, never free text.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import t
from app.core.models import AuditEvent

NEED_ORDER = "order"
NEED_DETAILS = "details"
# English text per need code (the templates themselves live in app/core/i18n.py).
QUESTIONS = {code: t(f"need.{code}") for code in (NEED_ORDER, NEED_DETAILS)}
GENERIC_QUESTION = t("need.generic")


def question_for(code: object, language: object = None) -> str:
    key = f"need.{code}" if code in (NEED_ORDER, NEED_DETAILS) else "need.generic"
    return t(key, language)


def need_from_payload(payload: object) -> str | None:
    code = payload.get("need") if isinstance(payload, dict) else None
    return code if isinstance(code, str) else None


def latest_question(session: Session, case_id: uuid.UUID, language: object = None) -> str:
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
    return question_for(need_from_payload(payload), language)
