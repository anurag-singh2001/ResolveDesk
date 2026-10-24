"""Domain events: an outbox table (domain_events) plus an in-process subscriber bus.

`emit` writes the event row in the caller's transaction and delivers it to subscribers in
that same transaction, so a state change and its consequences (e.g. the customer update on
the ticket) commit or roll back together. Each subscriber runs in a savepoint: one that fails
is logged and the event stays unpublished (published_at NULL) for `publish_pending` to retry,
so subscribers must be idempotent. Subscribers only touch the database; anything that calls a
provider must queue its own work and run outside the transaction (hard rule 5).

Subscribers live in feature modules (app/modules/...) and are loaded lazily by module name,
so core code never imports them (hard rule 2: extend through subscribers, not branches).
"""

import importlib
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.db import tenant_session
from app.core.models import DomainEvent

log = logging.getLogger(__name__)

Subscriber = Callable[[Session, DomainEvent], None]

# Modules that register subscribers when imported.
SUBSCRIBER_MODULES = ("app.modules.support.customer_updates",)

_SUBSCRIBERS: dict[str, list[Subscriber]] = {}
_loaded = False


def subscribe(*events: str) -> Callable[[Subscriber], Subscriber]:
    """Register a subscriber for exact event names (e.g. "case.verified")."""

    def register(fn: Subscriber) -> Subscriber:
        for name in events:
            handlers = _SUBSCRIBERS.setdefault(name, [])
            if fn not in handlers:
                handlers.append(fn)
        return fn

    return register


def subscribers(event: str) -> list[Subscriber]:
    _load()
    return list(_SUBSCRIBERS.get(event, ()))


def _load() -> None:
    global _loaded
    if not _loaded:
        for module in SUBSCRIBER_MODULES:
            importlib.import_module(module)
        _loaded = True


def emit(
    session: Session,
    tenant_id: uuid.UUID,
    event: str,
    entity_id: uuid.UUID | None,
    payload: dict[str, Any] | None = None,
) -> DomainEvent:
    """Record the event (tenant from the auth/system context) and deliver it now.
    Payloads hold ids and statuses only: no customer text or contact details."""
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a UUID from the auth/system context")
    row = DomainEvent(tenant_id=tenant_id, event=event, entity_id=entity_id, payload=payload or {})
    session.add(row)
    session.flush()
    _deliver(session, row)
    return row


def _deliver(session: Session, row: DomainEvent) -> bool:
    for handler in subscribers(row.event):
        nested = session.begin_nested()
        try:
            handler(session, row)
            session.flush()
        except Exception:
            nested.rollback()
            log.exception("subscriber %s failed on %s", handler.__name__, row.event)
            return False
        nested.commit()
    row.published_at = datetime.now(UTC)
    return True


def publish_pending(engine: Engine, tenant_id: uuid.UUID, limit: int = 100) -> int:
    """Re-deliver events whose subscribers failed earlier. Returns how many were published."""
    done = 0
    with tenant_session(tenant_id, engine) as s:
        rows = s.scalars(
            select(DomainEvent)
            .where(DomainEvent.published_at.is_(None), DomainEvent.event.in_(_names()))
            .order_by(DomainEvent.created_at, DomainEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            done += _deliver(s, row)
    return done


def _names() -> list[str]:
    _load()
    return [name for name, handlers in _SUBSCRIBERS.items() if handlers]
