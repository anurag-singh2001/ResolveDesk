"""The one "your erasure is complete" message (S8.8, owner decision P4).

Rules, in the order they matter:
- NEVER before success: the message is sent only for a request whose row is `completed`, and
  that status is set only by the executor (`data_rights.run_erasure`) after the redaction ran
  (hard rule 7).
- The customer's contact is wiped by the erasure, so the destination is copied at request
  time into an `erasure_notices` row: one row per request, this purpose only, deleted when the
  send reaches a final state (sent, failed, unknown) or, at the latest, at the first sweep after
  7 days from the request, whichever is
  first. It is the only place a destination outlives the erasure. It is never logged, audited
  or put in the receipt.
- The send goes out through the tenant's messaging connector with a stable key, outside any
  database transaction (hard rule 5). Running it again sends the same key (the provider
  de-duplicates) or does nothing once the outcome is stored, so it is idempotent.
- The text is a fixed template (hard rule 7): what was removed, what was kept and why, the
  privacy and grievance contact, and the Data Protection Board route. No name, order or amount.
- The outcome (`data_requests.completion_message`: sent | failed | unknown | expired | none) is
  the receipt. `unknown` is never shown as delivered. A request still deferred after the 7 days
  loses its destination and later records `expired`: we do not keep a contact longer to send it.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete, select

from app.connectors.base import connector_for
from app.core import audit
from app.core.db import tenant_session
from app.core.i18n import normalize, t
from app.core.models import Customer, DataRequest, ErasureNotice
from app.core.settings_resolver import effective_settings
from app.engine import data_held
from app.engine.dispatch import system_context
from app.engine.privacy import contact_line

log = logging.getLogger(__name__)

TTL = timedelta(days=7)
CHANNELS = ("phone", "email")
TEMPLATE = "erasure_completed"
# Connector answer -> stored outcome. "processing" and "unavailable" are not final: the row
# stays and the same key is retried by the sweeper until the 7 days run out.
FINAL_OUTCOME = {"succeeded": "sent", "failed": "failed", "unknown": "unknown"}


def held_channels(customer: Customer) -> list[str]:
    """Which destinations the customer has on file right now, phone first."""
    out = []
    if customer.phone:
        out.append("phone")
    if customer.email:
        out.append("email")
    return out


def capture(
    s, tenant_id: uuid.UUID, req: DataRequest, customer: Customer, via: str | None, now: datetime
) -> str:
    """Copy the chosen destination into the outbox at request time. `via` is the customer's
    pick (phone | email); anything else, or a pick they have no value for, falls back to the
    first they do have. Returns the channel used, or "none" (and records it) when they have
    none: the request screen says so before they confirm."""
    available = held_channels(customer)
    channel = via if via in available else (available[0] if available else None)
    if channel is None:
        req.completion_message = "none"
        return "none"
    s.add(
        ErasureNotice(
            tenant_id=tenant_id,
            request_id=req.id,
            channel=channel,
            destination=customer.phone if channel == "phone" else customer.email,
            language=normalize(customer.preferred_language),
            state="queued",
            expires_at=now + TTL,
        )
    )
    return channel


def drop(s, tenant_id: uuid.UUID, request_id: uuid.UUID) -> None:
    """The request ended without a send (withdrawn): the destination goes with it."""
    s.execute(
        delete(ErasureNotice).where(
            ErasureNotice.tenant_id == tenant_id, ErasureNotice.request_id == request_id
        )
    )


def reference(request_id: uuid.UUID) -> str:
    return str(request_id).split("-")[0].upper()


def completion_text(settings: dict[str, Any], lang: str, request_id: uuid.UUID) -> str:
    """The message, from templates only. The contact clause is left out while no contact is
    set, rather than pointing at nobody."""
    parts = [
        t("notice.done", lang, reference=reference(request_id)),
        t("notice.kept", lang, years=data_held._years(settings)),
    ]
    contact = contact_line(settings)
    if contact:
        parts.append(
            t("notice.contact", lang, contact=contact, days=data_held.target_days(settings))
        )
    parts.append(t("notice.board", lang))
    return " ".join(parts)


def _finish(s, tenant_id: uuid.UUID, req: DataRequest, notice: ErasureNotice | None, outcome: str):
    """Store the final state and remove the destination in the same transaction."""
    req.completion_message = outcome
    if notice is not None:
        s.delete(notice)
    audit.record(
        s,
        tenant_id,
        actor_type="system",
        actor_id=None,
        event="privacy.erasure_notice",
        entity_type="data_request",
        entity_id=req.id,
        payload={"outcome": outcome},  # never the destination
    )


def send_completion_notice(
    engine: Engine, tenant_id: uuid.UUID, request_id: uuid.UUID, now: datetime | None = None
) -> str | None:
    """Send the message for a completed request, once. Returns the stored outcome, or None when
    nothing final is known yet (not completed, or the provider has not answered)."""
    now = now or datetime.now(UTC)
    key = f"erasure-done:{request_id}"
    with tenant_session(tenant_id, engine) as s:
        req = s.scalar(
            select(DataRequest)
            .where(DataRequest.tenant_id == tenant_id, DataRequest.id == request_id)
            .with_for_update()
        )
        if req is None or req.status != "completed":
            return None  # never before the executor has succeeded
        if req.completion_message is not None:
            return req.completion_message  # already final: nothing to send twice
        notice = s.scalar(
            select(ErasureNotice)
            .where(ErasureNotice.tenant_id == tenant_id, ErasureNotice.request_id == request_id)
            .with_for_update()
        )
        if notice is None:  # the 7 days ran out first and the destination was removed
            _finish(s, tenant_id, req, None, "expired")
            return "expired"
        if notice.expires_at <= now:
            _finish(
                s, tenant_id, req, notice, "unknown" if notice.state == "sending" else "expired"
            )
            return req.completion_message
        settings = effective_settings(s)
        connector = connector_for(settings, "messaging")
        to, lang, channel = notice.destination, notice.language, notice.channel
        params = {
            "body": completion_text(settings, lang, request_id),
            "language": lang,
            "channel": channel,
        }
        notice.state = "sending"  # claimed; a crash after this retries with the same key
    outcome = None
    try:  # no transaction is open here (hard rule 5)
        sent = connector.send(system_context(tenant_id), key, to, TEMPLATE, params)
        outcome = FINAL_OUTCOME.get(sent.status)
    except Exception:
        log.exception("erasure notice %s: send raised", request_id)
        outcome = "unknown"  # the provider's answer is unknown; never "sent"
    if outcome is None:
        return None
    with tenant_session(tenant_id, engine) as s:
        req = s.scalar(
            select(DataRequest)
            .where(DataRequest.tenant_id == tenant_id, DataRequest.id == request_id)
            .with_for_update()
        )
        if req is None or req.completion_message is not None:
            return req.completion_message if req else None
        notice = s.scalar(
            select(ErasureNotice).where(
                ErasureNotice.tenant_id == tenant_id, ErasureNotice.request_id == request_id
            )
        )
        _finish(s, tenant_id, req, notice, outcome)
    return outcome


def sweep_notices(engine: Engine, tenant_id: uuid.UUID, now: datetime | None = None) -> list[str]:
    """Housekeeping for the sweeper: send (or retry) the message for every completed request
    that still has an outbox row, and delete expired destinations of requests that never
    completed. Returns the request ids it acted on."""
    now = now or datetime.now(UTC)
    with tenant_session(tenant_id, engine) as s:
        s.execute(
            delete(ErasureNotice).where(
                ErasureNotice.tenant_id == tenant_id,
                ErasureNotice.expires_at <= now,
                ErasureNotice.request_id.in_(
                    select(DataRequest.id).where(
                        DataRequest.tenant_id == tenant_id, DataRequest.status != "completed"
                    )
                ),
            )
        )
        pending = list(
            s.scalars(
                select(ErasureNotice.request_id)
                .join(
                    DataRequest,
                    (DataRequest.id == ErasureNotice.request_id)
                    & (DataRequest.tenant_id == ErasureNotice.tenant_id),
                )
                .where(
                    ErasureNotice.tenant_id == tenant_id,
                    DataRequest.status == "completed",
                    DataRequest.completion_message.is_(None),
                )
            )
        )
    done = []
    for request_id in pending:
        try:
            send_completion_notice(engine, tenant_id, request_id, now)
        except Exception:
            log.exception("erasure notice %s: could not send", request_id)
        done.append(str(request_id))
    return done
