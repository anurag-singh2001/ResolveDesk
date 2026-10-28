"""Staff replies to the customer and closing a case (S7.6).

Hard rule 7: a customer reads only verified facts. So a staff reply is one of
- a code-owned template (app/core/i18n.py), rendered in the case language, with any figure
  filled by code from the proposal, never typed; and
- an optional short free-text note. The note is staff-authored (never a model), length-limited,
  stored and shown verbatim under its own "From our team" label, is a separate message from the
  template (never spliced into template text), and may not state money or contain links
  (_check_note). That filter is a guard, not a proof; the label tells the customer who wrote it.

Both go on the case's ticket as author "staff" and are audited with the template id and the
note's length only, never the words. A double submit is one message (idempotency key).
Closing refuses unless every proposal is rejected or its payout is confirmed (and while an AI
re-run is in progress), so a payout is never stranded or hidden behind a closed case.
"""

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.i18n import case_language, t
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Execution,
    RefundOperation,
    Ticket,
    TicketMessage,
    Verification,
)
from app.core.money import format_inr
from app.core.tenancy import TenantContext
from app.engine import ai_rerun
from app.engine.approvals import not_superseded
from app.engine.case_status import case_status, is_payout_confirmed

NOTE_MAX_LENGTH = 280
CLOSE_REASONS = {
    "resolved": "Resolved",
    "no_remedy": "No remedy due",
    "duplicate": "Duplicate of another case",
    "unreachable": "Customer unreachable",
}
# template id -> (label shown to staff, i18n key). Order is the order shown.
TEMPLATE_IDS = {
    "looking_into": ("We're looking into it", "staff.looking_into"),
    "share_photo": ("Please share a photo", "staff.share_photo"),
    "passed_to_outlet": ("We've passed this to the outlet", "staff.passed_to_outlet"),
    "refund_processing": ("Your refund is processing", "staff.refund_processing"),
}

# What a note may not say: anything about money (the system, not staff, states those facts) and
# links. Latin words are matched on word boundaries ("orders" is fine, "rs" is not); Devanagari
# has no reliable word boundary, so those stems are substring matches. The text is
# NFKC-normalised and zero-width / format characters are removed first, so a hidden character
# inside "refund" cannot slip through.
_MONEY_LATIN = re.compile(
    r"\b(rs|inr|upi|cash\w*|pay\w*|paid|refund\w*|rifund\w*|voucher\w*|credit\w*|debit\w*"
    r"|charge[ds]?|amount\w*|money|paisa|paise|rupee\w*|rupaye|bhugtan|reimburs\w*"
    r"|compensat\w*|wallet|revers\w*|bank\w*|card)\b",
    re.IGNORECASE,
)
_MONEY_DEVANAGARI = ("रिफ", "वाउचर", "पैसे", "पैसा", "भुगतान", "रुपय", "क्रेडिट", "₹")
_DIGIT_RUN = re.compile(r"\d{3,}")
_LINK = re.compile(r"https?:|www\.|\.com\b|\.in\b|@\w", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class StaffActionError(Exception):
    pass


class CaseClosed(StaffActionError):
    """The case is already closed."""


class PayoutInFlight(StaffActionError):
    """A proposal is waiting for a decision, or approved and not yet finished."""


class ReplayMismatch(StaffActionError):
    """The idempotency key was already used for a different message."""


class BadTemplate(StaffActionError):
    """Unknown template, or one that does not apply to this case right now."""


class BadNote(StaffActionError):
    """The free text breaks a rule (length, money words, links)."""


@dataclass(frozen=True)
class TemplateOption:
    id: str
    label: str
    preview: str


def _refund_in_progress(session: Session, case: Case, now: datetime) -> int | None:
    """The refund amount if (and only if) the customer-facing status is 'processing' for a
    refund: the one money state this template may state."""
    st = case_status(session, case, now)
    if st.stage == "processing" and st.action == "refund" and st.amount_paise:
        return st.amount_paise
    return None


def available_templates(
    session: Session, case: Case, now: datetime, language: str | None = None
) -> list[TemplateOption]:
    lang = language or case_language(session, case)
    options = []
    for tid, (label, key) in TEMPLATE_IDS.items():
        params = {}
        if tid == "refund_processing":
            amount = _refund_in_progress(session, case, now)
            if amount is None:
                continue
            params["amount"] = format_inr(amount)
        options.append(TemplateOption(tid, label, t(key, lang, **params)))
    return options


def _check_note(note: str | None) -> str | None:
    if note is None:
        return None
    note = "".join(
        ch for ch in unicodedata.normalize("NFKC", note) if unicodedata.category(ch) != "Cf"
    ).strip()
    if not note:
        return None
    if len(note) > NOTE_MAX_LENGTH:
        raise BadNote(f"the note is limited to {NOTE_MAX_LENGTH} characters")
    if _CONTROL.search(note):
        raise BadNote("the note contains characters that are not allowed")
    if (
        _MONEY_LATIN.search(note)
        or any(w in note for w in _MONEY_DEVANAGARI)
        or _DIGIT_RUN.search(note)
    ):
        raise BadNote(
            "a note cannot talk about money, refunds or payments; "
            "use a template so the figures come from the system"
        )
    if _LINK.search(note):
        raise BadNote("a note cannot contain links or addresses")
    return note


def _lock_case(session: Session, case: Case) -> Case:
    return session.execute(
        select(Case)
        .where(Case.id == case.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _ticket_id(session: Session, case: Case) -> uuid.UUID | None:
    return session.scalar(select(Ticket.id).where(Ticket.case_id == case.id))


DOUBLE_SUBMIT_WINDOW = timedelta(seconds=10)


def _recent_duplicate(
    session: Session,
    ticket_id: uuid.UUID,
    user_id: uuid.UUID,
    template_id: str,
    note: str | None,
    now: datetime,
) -> bool:
    for msg in session.scalars(
        select(TicketMessage).where(
            TicketMessage.ticket_id == ticket_id,
            TicketMessage.kind == "template",
            TicketMessage.sender_user_id == user_id,
            TicketMessage.template_id == template_id,
            TicketMessage.sent_at >= now - DOUBLE_SUBMIT_WINDOW,
        )
    ):
        stored = session.scalar(
            select(TicketMessage.body).where(
                TicketMessage.idempotency_key == (msg.idempotency_key or "") + ":note"
            )
        )
        if stored == note:
            return True
    return False


def send_reply(
    session: Session,
    ctx: TenantContext,
    case: Case,
    *,
    template_id: str,
    note: str | None,
    idempotency_key: str | None,
    now: datetime,
    clock: datetime | None = None,
) -> bool:
    """Send a templated reply (and optional note). Returns False when this exact submit was
    already stored (a double submit): nothing is added or audited twice. `now` stamps the
    write (real time); `clock` (the app clock, default `now`) decides what the case's status is,
    the same clock the template list used. The caller has checked the case is in scope."""
    clock = clock or now
    if template_id not in TEMPLATE_IDS:
        raise BadTemplate("unknown template")
    note = _check_note(note)
    case = _lock_case(session, case)
    ticket_id = _ticket_id(session, case)
    if ticket_id is None:
        raise StaffActionError("this case has no conversation to add to")
    if idempotency_key:
        # The key is bound to what was sent: the same key with other content is a client bug
        # (or a stale form), not a retry, so it is refused instead of silently dropped.
        digest = hashlib.sha256(f"{template_id}|{note or ''}".encode()).hexdigest()[:16]
        prefix = f"staff-reply:{case.id}:{idempotency_key}:"
        key = prefix + digest
        stored = session.scalar(
            select(TicketMessage.idempotency_key)
            .where(
                TicketMessage.idempotency_key.startswith(prefix, autoescape=True),
                TicketMessage.kind == "template",
            )
            .limit(1)
        )
        if stored is not None:
            if stored != key:
                raise ReplayMismatch("this key was already used for a different message")
            return False
    else:
        # No client key: the same sender, template and note within a few seconds is a double
        # submit. A later identical reply is a new, deliberate message.
        key = f"staff-reply:{case.id}:{uuid.uuid4().hex}"
        if _recent_duplicate(session, ticket_id, ctx.user_id, template_id, note, now):
            return False
    if case.status == "closed":
        raise CaseClosed("this case is closed")
    lang = case_language(session, case)
    key_name = TEMPLATE_IDS[template_id][1]
    params = {}
    if template_id == "refund_processing":
        amount = _refund_in_progress(session, case, clock)
        if amount is None:
            raise BadTemplate("this template does not apply: no refund is being processed")
        params["amount"] = format_inr(amount)
    session.add(
        TicketMessage(
            tenant_id=ctx.tenant_id,
            ticket_id=ticket_id,
            author="staff",
            body=t(key_name, lang, **params),
            sent_at=now,
            kind="template",
            template_id=template_id,
            sender_user_id=ctx.user_id,
            idempotency_key=key,
        )
    )
    if note:
        session.add(
            TicketMessage(
                tenant_id=ctx.tenant_id,
                ticket_id=ticket_id,
                author="staff",
                body=note,
                sent_at=now + timedelta(microseconds=1),  # after its template, always
                kind="note",
                sender_user_id=ctx.user_id,
                idempotency_key=key + ":note",
            )
        )
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.staff_reply",
        entity_type="case",
        entity_id=case.id,
        # Never the words: the template id and the note's length are enough to review it.
        payload={"template_id": template_id, "addendum_length": len(note) if note else 0},
    )
    return True


def payout_unsettled(session: Session, case: Case) -> bool:
    """True unless every proposal on the case is over: rejected, or its payout confirmed by the
    same predicate the customer status uses (case_status.is_payout_confirmed), and no refund
    left pending reconciliation. So an undecided, approved-not-run, failed, unverified or
    mismatched payout all block a close: a customer is never told "closed" over money that
    has not been confirmed (hard rule 7)."""
    for proposal in session.scalars(
        select(ActionProposal).where(ActionProposal.case_id == case.id, not_superseded())
    ):  # a switched-away proposal is not owed anything (S7.10)
        approval = session.scalar(select(Approval).where(Approval.proposal_id == proposal.id))
        if approval is None:
            return True
        if approval.decision == "rejected":
            continue
        execution = session.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
        verification = (
            session.scalars(
                select(Verification.status)
                .where(Verification.execution_id == execution.id)
                .order_by(Verification.created_at.desc(), Verification.id)
            ).first()
            if execution is not None
            else None
        )
        if not is_payout_confirmed(proposal.action, execution, verification):
            return True
        ledger = session.scalar(
            select(RefundOperation.status).where(RefundOperation.proposal_id == proposal.id)
        )
        if ledger == "pending_reconciliation":
            return True
    return False


def close_case(
    session: Session, ctx: TenantContext, case: Case, *, reason: str, now: datetime
) -> None:
    if reason not in CLOSE_REASONS:
        raise StaffActionError("unknown close reason")
    case = _lock_case(session, case)
    if case.status == "closed":
        raise CaseClosed("this case is already closed")
    if case.status == "investigating" and ai_rerun.unfinished_request(session, case.id):
        raise PayoutInFlight("the AI is being run again on this case; wait for it to finish")
    if payout_unsettled(session, case):
        raise PayoutInFlight(
            "a remedy on this case is waiting for a decision, still being carried out, "
            "or not confirmed; settle it first"
        )
    case.status = "closed"
    case.close_reason = reason
    case.closed_at = now
    case.closed_by_user_id = ctx.user_id
    for ticket in session.scalars(select(Ticket).where(Ticket.case_id == case.id)):
        ticket.status = "closed"
        ticket.closed_at = now
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.closed",
        entity_type="case",
        entity_id=case.id,
        payload={"reason": reason},
    )
    events.emit(session, ctx.tenant_id, "case.closed", case.id, {"reason": reason})
