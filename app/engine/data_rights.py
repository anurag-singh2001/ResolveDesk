"""Customer data rights (S5.2): consent history, access export, erasure.

Provisional (pending the owner's confirmation; not legal advice): support needs no consent
record; marketing/growth messages need a granted one; nomination and consent managers are out.

Erasure is code-only (hard rule 4) and reuses the retention guards (app/engine/retention.py):
it never runs while anything is in flight, a case is held, or the customer is inside the
one-year floor. Those cases show as `deferred` with a reason, never silently dropped. When it
runs it redacts like retention does (message text, contact data, login identity); money rows,
proposals, approvals, executions, refund operations and audit_events are not touched.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import (
    Case,
    Consent,
    ConsentEvent,
    Customer,
    DataRequest,
    RefundOperation,
    Ticket,
    TicketMessage,
    Transaction,
    User,
)
from app.engine import erasure_notice
from app.engine.retention import (
    FINISHED,
    MESSAGE_MARKER,
    MIN_DAYS,
    NAME_MARKER,
    REFUND_IN_FLIGHT,
    unsettled_case_ids,
)

NOTICE_VERSION = "2026-10-v1"
PURPOSES = ("marketing",)  # support is not consent-based (provisional decision)
CHANNELS = ("whatsapp",)  # the only channel growth sends on today

# Customer-facing wording for a deferred request (templates, hard rule 7: no invented facts).
REASONS = {
    "open_case": (
        "You have a case that is still being handled. We can erase your data once it is closed."
    ),
    "in_flight": (
        "A refund or payment linked to your orders is still being processed. "
        "We will revisit your request once it has settled."
    ),
    "legal_hold": (
        "Some of your records are on hold and must be kept for now. "
        "A member of our team will follow up."
    ),
    "retention_floor": (
        "We must keep some records for at least one year after your last activity. "
        "Your request can go ahead after {date}."
    ),
}
ACTIVE = ("pending_approval", "deferred")


@dataclass(frozen=True)
class Block:
    code: str
    until: datetime | None = None

    def text(self) -> str:
        date = self.until.date().isoformat() if self.until else ""
        return REASONS[self.code].format(date=date)


def reason_text(code: str | None, until: datetime | None) -> str | None:
    if code is None or code not in REASONS:
        return None
    return Block(code, until).text()


def erasure_block(
    s: Session, tenant_id: uuid.UUID, customer_id: uuid.UUID, now: datetime
) -> Block | None:
    """Why this customer cannot be erased now, or None. The first reason wins, in the order
    in-progress work, in-flight money, legal hold, one-year floor."""
    cases = select(Case.id).where(Case.tenant_id == tenant_id, Case.customer_id == customer_id)
    open_case = exists().where(
        Case.tenant_id == tenant_id,
        Case.customer_id == customer_id,
        Case.status.not_in(FINISHED),  # escalated counts as open: a person is still on it
    )
    open_ticket = exists().where(
        Ticket.tenant_id == tenant_id,
        Ticket.customer_id == customer_id,
        Ticket.status.in_(("open", "escalated")),
    )
    if s.scalar(select(open_case | open_ticket)):
        return Block("open_case")
    in_flight = exists().where(
        Case.id.in_(unsettled_case_ids(tenant_id)), Case.id.in_(cases)
    ) | exists().where(
        RefundOperation.tenant_id == tenant_id,
        RefundOperation.status.in_(REFUND_IN_FLIGHT),
        RefundOperation.transaction_id.in_(
            select(Transaction.id).where(
                Transaction.tenant_id == tenant_id, Transaction.customer_id == customer_id
            )
        ),
    )
    if s.scalar(select(in_flight)):
        return Block("in_flight")
    if s.scalar(select(exists().where(Case.id.in_(cases), Case.legal_hold.is_(True)))):
        return Block("legal_hold")
    last_case = s.scalar(
        select(Case.updated_at)
        .where(Case.tenant_id == tenant_id, Case.customer_id == customer_id)
        .order_by(Case.updated_at.desc())
        .limit(1)
    )
    last_order = s.scalar(
        select(Transaction.placed_at)
        .where(Transaction.tenant_id == tenant_id, Transaction.customer_id == customer_id)
        .order_by(Transaction.placed_at.desc())
        .limit(1)
    )
    last = max((t for t in (last_case, last_order) if t is not None), default=None)
    if last is not None and last + timedelta(days=MIN_DAYS) > now:
        return Block("retention_floor", last + timedelta(days=MIN_DAYS))
    return None


# --- consent ----------------------------------------------------------------------------


def set_consent(
    s: Session,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    purpose: str,
    channel: str,
    granted: bool,
    source: str = "customer",
    actor_id: uuid.UUID | None = None,
) -> bool:
    """Make the current state `granted` and append a history row when anything changed (or
    nothing was recorded before, so a first withdrawal is evidence too). Returns whether a
    history row was added. `consents` is unique per (tenant, customer, channel, purpose); two
    simultaneous first decisions race on that key, so the insert runs in a savepoint and the
    loser updates the winner's row instead."""

    def current() -> Consent | None:
        return s.scalar(
            select(Consent)
            .where(
                Consent.tenant_id == tenant_id,
                Consent.customer_id == customer_id,
                Consent.channel == channel,
                Consent.purpose == purpose,
            )
            .with_for_update()
        )

    row = current()
    if row is None:
        try:
            with s.begin_nested():
                s.add(
                    Consent(
                        tenant_id=tenant_id,
                        customer_id=customer_id,
                        channel=channel,
                        purpose=purpose,
                        granted=granted,
                    )
                )
                s.flush()
        except IntegrityError:  # someone else recorded the first decision just now
            row = current()
            if row is None:
                raise
            if row.granted == granted:
                return False
            row.granted = granted
    elif row.granted == granted:
        return False
    else:
        row.granted = granted
    s.add(
        ConsentEvent(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel=channel,
            purpose=purpose,
            granted=granted,
            source=source,
            notice_version=NOTICE_VERSION,
        )
    )
    audit.record(
        s,
        tenant_id,
        actor_type="user" if source == "customer" else "system",
        actor_id=actor_id,
        event="consent.granted" if granted else "consent.withdrawn",
        entity_type="customer",
        entity_id=customer_id,
        payload={"purpose": purpose, "channel": channel},
    )
    return True


# --- erasure ----------------------------------------------------------------------------


def _active_request(s: Session, tenant_id: uuid.UUID, customer_id: uuid.UUID):
    return s.scalar(
        select(DataRequest).where(
            DataRequest.tenant_id == tenant_id,
            DataRequest.customer_id == customer_id,
            DataRequest.status.in_(ACTIVE),
        )
    )


def request_erasure(
    s: Session,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    now: datetime,
    actor_id: uuid.UUID | None = None,
    notify_via: str | None = None,
) -> DataRequest:
    """File a request (one active request per customer, also enforced by a partial unique
    index: a simultaneous second call gets the first one back). If it cannot run now it is
    created already `deferred` with the reason; otherwise it waits for a person to approve.
    `notify_via` (phone | email) picks where the one completion message goes; the destination
    is copied into a short-lived outbox row now, because the erasure wipes the contact."""
    existing = _active_request(s, tenant_id, customer_id)
    if existing is not None:
        return existing
    block = erasure_block(s, tenant_id, customer_id, now)
    req = DataRequest(
        tenant_id=tenant_id,
        customer_id=customer_id,
        kind="erasure",
        status="deferred" if block else "pending_approval",
        reason_code=block.code if block else None,
        deferred_until=block.until if block else None,
    )
    try:
        with s.begin_nested():
            s.add(req)
            s.flush()
    except IntegrityError:
        existing = _active_request(s, tenant_id, customer_id)
        if existing is None:
            raise
        return existing
    customer = s.get(Customer, customer_id)
    channel = erasure_notice.capture(s, tenant_id, req, customer, notify_via, now)
    s.flush()
    audit.record(
        s,
        tenant_id,
        actor_type="user",
        actor_id=actor_id,
        event="privacy.erasure_requested",
        entity_type="data_request",
        entity_id=req.id,
        # The channel kind only (phone | email | none), never the destination.
        payload={"status": req.status, "reason": req.reason_code, "notify_channel": channel},
    )
    return req


def withdraw_erasure(
    s: Session,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> DataRequest | None:
    """The customer takes back their open request. Returns the request (already withdrawn
    counts as success), or None when they have no request. A completed request cannot be
    withdrawn: the caller gets it back unchanged and must say so. The row is locked like
    run_erasure locks it, so a withdrawal and an approval cannot both win: whichever commits
    second sees the other's final state."""
    req = s.scalar(
        select(DataRequest)
        .where(DataRequest.tenant_id == tenant_id, DataRequest.customer_id == customer_id)
        .order_by(DataRequest.created_at.desc(), DataRequest.id)
        .limit(1)
        .with_for_update()
    )
    if req is None or req.status in ("completed", "withdrawn"):
        return req
    req.status, req.reason_code, req.deferred_until = "withdrawn", None, None
    erasure_notice.drop(s, tenant_id, req.id)  # no send will happen: the destination goes now
    audit.record(
        s,
        tenant_id,
        actor_type="user",
        actor_id=actor_id,
        event="privacy.erasure_withdrawn",
        entity_type="data_request",
        entity_id=req.id,
        payload={},
    )
    return req


def run_erasure(
    s: Session,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    now: datetime,
    guard: Callable[[DataRequest], None] | None = None,
) -> DataRequest | None:
    """Approve and execute (or re-defer) a request. None if it does not exist. Idempotent: a
    completed request is returned unchanged. `guard` (the staff approval check, S8.5e) runs
    after the request and the customer are locked and before anything is checked or changed;
    it raises to refuse, so an approval cannot go stale between its check and the redaction."""
    req = s.scalar(
        select(DataRequest)
        .where(DataRequest.tenant_id == tenant_id, DataRequest.id == request_id)
        .with_for_update()
    )
    if req is None or req.status in ("completed", "withdrawn"):
        return req  # a withdrawn request never runs, even if a person approves it later
    # Lock the customer before checking the guards and keep it until commit: case writes take
    # a share lock on the same row (engine/cases.lock_customer), so nothing new can start
    # between the check and the redaction.
    s.execute(
        select(Customer.id)
        .where(Customer.tenant_id == tenant_id, Customer.id == req.customer_id)
        .with_for_update()
    )
    if guard is not None:
        guard(req)
    block = erasure_block(s, tenant_id, req.customer_id, now)
    if block is not None:
        req.status, req.reason_code, req.deferred_until = "deferred", block.code, block.until
        audit.record(
            s,
            tenant_id,
            actor_type="user",
            actor_id=actor_id,
            event="privacy.erasure_deferred",
            entity_type="data_request",
            entity_id=req.id,
            payload={"reason": block.code},
        )
        return req
    _redact(s, tenant_id, req.customer_id, now)
    req.status, req.reason_code, req.deferred_until = "completed", None, None
    req.decided_by, req.completed_at = actor_id, now
    audit.record(
        s,
        tenant_id,
        actor_type="user",
        actor_id=actor_id,
        event="privacy.erasure_completed",
        entity_type="data_request",
        entity_id=req.id,
        payload={"customer_id": str(req.customer_id)},
    )
    return req


def _redact(s: Session, tenant_id: uuid.UUID, customer_id: uuid.UUID, now: datetime) -> None:
    tickets = select(Ticket.id).where(
        Ticket.tenant_id == tenant_id, Ticket.customer_id == customer_id
    )
    s.execute(
        update(TicketMessage)
        .where(TicketMessage.tenant_id == tenant_id, TicketMessage.ticket_id.in_(tickets))
        .values(body=MESSAGE_MARKER)
    )
    user_id = s.scalar(select(Customer.user_id).where(Customer.id == customer_id))
    s.execute(
        update(Customer)
        .where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
        .values(phone=None, email=None, name=NAME_MARKER, attributes={})
    )
    if user_id is not None:  # the login identity: no way back in, no contact address left
        s.execute(
            update(User)
            .where(User.tenant_id == tenant_id, User.id == user_id)
            .values(
                email=f"erased-{user_id}@erased.invalid",
                display_name=NAME_MARKER,
                password_hash=None,
                password_is_demo=False,
                erased_at=now,  # load_context now refuses any token for this user
            )
        )
    for row in list(
        s.scalars(
            select(Consent).where(
                Consent.tenant_id == tenant_id, Consent.customer_id == customer_id
            )
        )
    ):
        set_consent(s, tenant_id, customer_id, row.purpose, row.channel, False, source="erasure")
