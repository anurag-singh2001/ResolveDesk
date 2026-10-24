"""Append-only audit trail (audit_events). Payloads are redacted before they are stored."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import AuditEvent

REDACTED_KEYS = frozenset({"phone", "email", "name", "to", "address", "message", "body"})


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[redacted]" if k in REDACTED_KEYS else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def record(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    actor_type: str,
    actor_id: uuid.UUID | str | None,
    event: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=redact(payload or {}),
        )
    )
