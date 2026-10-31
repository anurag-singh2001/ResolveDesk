"""Owner-side privacy request queue (S8.5e, R5).

Staff (hq_owner) see open erasure requests with stage, dates and the reason for a deferral, a
dry run of what an erasure would remove and keep (counts only, never message text), and approve
with an approval that is bound to the dry run and expires.

- The approval is stateless: an HMAC over (tenant, request, approver, payload hash, expiry).
  The hash covers the request state and every count in the dry run, so if the customer's data
  or the request changes after the owner looked, the hash differs and the approval is stale.
  The check runs inside `run_erasure` (the `guard` hook) after it locks the request and the
  customer, so nothing can change between the check and the redaction. There is no second
  write path: the executor is still `data_rights.run_erasure`.
- Counts and audit payloads carry no personal content.
- The sweeper warns once when a request reaches 75% of the target and once when it is overdue
  (audit rows, like grievance.due_soon); a request that leaves the open list stops being flagged.
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Consent,
    ConsentEvent,
    Customer,
    DataRequest,
    Execution,
    RefundOperation,
    Ticket,
    TicketMessage,
    Transaction,
    User,
)
from app.core.settings_resolver import effective_settings
from app.engine import data_held, erasure_info
from app.engine import data_rights as privacy
from app.engine.retention import MESSAGE_MARKER, NAME_MARKER

APPROVAL_TTL = timedelta(minutes=30)
DUE_SOON_FRACTION = 0.75
DUE_SOON_EVENT = "privacy.erasure_due_soon"
OVERDUE_EVENT = "privacy.erasure_overdue"
OPEN = privacy.ACTIVE


class StaleApproval(Exception):
    """The approval is missing, forged, expired, or the request changed since the dry run."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code  # missing | invalid | expired | changed


def mask_ref(ref: str) -> str:
    """Enough to recognise a record, not enough to identify a person at a glance."""
    return ref if len(ref) <= 4 else f"{ref[:2]}{'*' * (len(ref) - 4)}{ref[-2:]}"


# --- dry run ----------------------------------------------------------------------------


def _count(s: Session, stmt) -> int:
    return int(s.scalar(stmt) or 0)


def dry_run(s: Session, tenant_id: uuid.UUID, req: DataRequest, now: datetime) -> dict[str, Any]:
    """Exactly what `run_erasure` would remove and keep for this customer, as counts. The
    `remove` keys mirror data_rights._redact; the `keep` keys mirror what it leaves alone.
    Counts only: no names, contact data or message text."""
    cid = req.customer_id
    customer = s.get(Customer, cid)
    tickets = select(Ticket.id).where(Ticket.tenant_id == tenant_id, Ticket.customer_id == cid)
    cases = select(Case.id).where(Case.tenant_id == tenant_id, Case.customer_id == cid)
    proposals = select(ActionProposal.id).where(ActionProposal.case_id.in_(cases))
    orders = select(Transaction.id).where(
        Transaction.tenant_id == tenant_id, Transaction.customer_id == cid
    )
    user = s.get(User, customer.user_id) if customer and customer.user_id else None
    remove = {
        "messages": _count(
            s,
            select(func.count()).where(
                TicketMessage.tenant_id == tenant_id,
                TicketMessage.ticket_id.in_(tickets),
                TicketMessage.body != MESSAGE_MARKER,
            ),
        ),
        "name": int(bool(customer and customer.name and customer.name != NAME_MARKER)),
        "contact_fields": int(bool(customer and customer.phone))
        + int(bool(customer and customer.email)),
        "profile_fields": len((customer.attributes or {}) if customer else {}),
        "login": int(bool(user and user.erased_at is None)),
        "marketing_consents": _count(
            s,
            select(func.count()).where(
                Consent.tenant_id == tenant_id,
                Consent.customer_id == cid,
                Consent.granted.is_(True),
            ),
        ),
    }
    keep = {
        "orders": _count(s, select(func.count()).select_from(orders.subquery())),
        "refund_operations": _count(
            s,
            select(func.count()).where(
                RefundOperation.tenant_id == tenant_id,
                RefundOperation.transaction_id.in_(orders),
            ),
        ),
        "cases": _count(s, select(func.count()).select_from(cases.subquery())),
        "tickets": _count(s, select(func.count()).select_from(tickets.subquery())),
        "proposals": _count(s, select(func.count()).select_from(proposals.subquery())),
        "approvals": _count(s, select(func.count()).where(Approval.proposal_id.in_(proposals))),
        "executions": _count(s, select(func.count()).where(Execution.proposal_id.in_(proposals))),
        "consent_history": _count(
            s,
            select(func.count()).where(
                ConsentEvent.tenant_id == tenant_id, ConsentEvent.customer_id == cid
            ),
        ),
    }
    block = privacy.erasure_block(s, tenant_id, cid, now)
    deferred = (
        {
            "code": block.code,
            "until": block.until.date().isoformat() if block.until else None,
            "reason": block.text(),
        }
        if block
        else None
    )
    basis = {
        "request_id": str(req.id),
        "customer_id": str(cid),
        "status": req.status,
        "remove": remove,
        "keep": keep,
        "deferred": deferred and {"code": deferred["code"], "until": deferred["until"]},
    }
    return {
        "request_id": str(req.id),
        "status": req.status,
        "remove": remove,
        "keep": keep,
        "deferred": deferred,
        "payload_hash": hashlib.sha256(
            json.dumps(basis, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


# --- the bound, expiring approval ---------------------------------------------------------


def _mac(tenant_id: uuid.UUID, request_id: uuid.UUID, approver: uuid.UUID, h: str, exp: int) -> str:
    msg = f"privacy-erasure|{tenant_id}|{request_id}|{approver}|{h}|{exp}".encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()


def _key() -> bytes:
    """A key derived for this one purpose, so the login signing secret is never used directly
    and a token from one purpose cannot be replayed as another."""
    root = get_settings().jwt_secret.encode()
    return hmac.new(root, b"resolvedesk/privacy-erasure-approval/v1", hashlib.sha256).digest()


def issue_approval(
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    approver: uuid.UUID,
    payload_hash: str,
    now: datetime,
) -> tuple[str, datetime]:
    expires = now + APPROVAL_TTL
    exp = int(expires.timestamp())
    return f"{exp}.{_mac(tenant_id, request_id, approver, payload_hash, exp)}", expires


def check_approval(
    s: Session,
    tenant_id: uuid.UUID,
    req: DataRequest,
    approver: uuid.UUID,
    payload_hash: str | None,
    token: str | None,
    now: datetime,
) -> None:
    """Raises StaleApproval unless the token is genuine, unexpired, issued to this approver for
    this request and hash, and the hash still equals the request's current dry run."""
    if not payload_hash or not token:
        raise StaleApproval("missing")
    exp_text, _, mac = token.partition(".")
    if not exp_text.isdigit():
        raise StaleApproval("invalid")
    exp = int(exp_text)
    good = _mac(tenant_id, req.id, approver, payload_hash, exp)
    if not hmac.compare_digest(good, mac):
        raise StaleApproval("invalid")
    if now.timestamp() >= exp:
        raise StaleApproval("expired")
    if dry_run(s, tenant_id, req, now)["payload_hash"] != payload_hash:
        raise StaleApproval("changed")


def record_review(s: Session, tenant_id: uuid.UUID, actor: uuid.UUID, req: DataRequest) -> None:
    audit.record(
        s,
        tenant_id,
        actor_type="user",
        actor_id=actor,
        event="privacy.erasure_reviewed",
        entity_type="data_request",
        entity_id=req.id,
        payload={"status": req.status},
    )


def record_approval(
    s: Session, tenant_id: uuid.UUID, actor: uuid.UUID, req: DataRequest, payload_hash: str
) -> None:
    audit.record(
        s,
        tenant_id,
        actor_type="user",
        actor_id=actor,
        event="privacy.erasure_approved",
        entity_type="data_request",
        entity_id=req.id,
        payload={"payload_hash": payload_hash},
    )


# --- the queue --------------------------------------------------------------------------


def queue(s: Session, now: datetime) -> dict[str, Any]:
    """Open erasure requests, oldest first (nearest its target on top). Withdrawn and
    completed requests are not here. Customers are shown by masked reference only."""
    days = data_held.target_days(effective_settings(s))
    rows = s.execute(
        select(DataRequest, Customer.external_ref)
        .join(Customer, Customer.id == DataRequest.customer_id)
        .where(DataRequest.status.in_(OPEN))
        .order_by(DataRequest.created_at, DataRequest.id)
        .limit(200)
    ).all()
    items = []
    for req, ref in rows:
        target = req.created_at + timedelta(days=days)
        items.append(
            {
                "id": str(req.id),
                "kind": req.kind,
                "customer_ref": mask_ref(ref),
                "status": req.status,
                "stage": erasure_info.STAGE[req.status],
                "received_at": req.created_at,
                "target_at": target,
                "days_left": (target - now).days,  # floors: negative once past the target
                "overdue": now > target,
                "deferred_until": req.deferred_until,
                "reason_code": req.reason_code,
                "reason": privacy.reason_text(req.reason_code, req.deferred_until),
            }
        )
    return {"target_days": days, "items": items}


def flag_due(engine: Engine, tenant_id: uuid.UUID, now: datetime) -> list[str]:
    """Audit `privacy.erasure_due_soon` once per open request past 75% of the target and
    `privacy.erasure_overdue` once when it passes the target. Payloads have no personal data."""
    flagged: list[str] = []
    with tenant_session(tenant_id, engine) as s:
        days = data_held.target_days(effective_settings(s))
        for event, cutoff in (
            (DUE_SOON_EVENT, now - timedelta(days=days * DUE_SOON_FRACTION)),
            (OVERDUE_EVENT, now - timedelta(days=days)),
        ):
            already = select(AuditEvent.id).where(
                AuditEvent.event == event,
                AuditEvent.entity_type == "data_request",
                AuditEvent.entity_id == DataRequest.id,
            )
            reqs = s.scalars(
                select(DataRequest)
                .where(
                    DataRequest.status.in_(OPEN),
                    DataRequest.created_at <= cutoff,
                    ~already.exists(),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for req in reqs:
                audit.record(
                    s,
                    tenant_id,
                    actor_type="system",
                    actor_id=None,
                    event=event,
                    entity_type="data_request",
                    entity_id=req.id,
                    payload={"target_days": days, "status": req.status},
                )
                flagged.append(str(req.id))
    return flagged
