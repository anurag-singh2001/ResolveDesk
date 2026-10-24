"""Append-only audit trail (audit_events). Payloads are redacted before they are stored."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import AuditEvent

# Key fragments matched case-insensitively ("customer_phone", "Phone", "email_address"...).
REDACTED_FRAGMENTS = ("phone", "email", "name", "address", "message", "body", "note", "text")
REDACTED_EXACT = frozenset({"to"})


def _sensitive(key: str) -> bool:
    k = key.lower()
    return k in REDACTED_EXACT or any(fragment in k for fragment in REDACTED_FRAGMENTS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: "[redacted]" if isinstance(k, str) and _sensitive(k) else redact(v)
            for k, v in value.items()
        }
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
