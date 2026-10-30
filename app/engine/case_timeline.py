"""Customer-safe history of a case (GET /cases/{id}/timeline).

Every step is derived from rows (case, audit events, proposal, approval, execution, refund
ledger) and every text is a template in this file: no model output, no policy text, no
internal reasons ever reach it. Like case_status (hard rule 7), money is only "processed"
once the provider reported success; a decision is not money having moved.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import TEMPLATES, case_language, t
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Execution,
    RefundOperation,
    Ticket,
    TicketMessage,
)
from app.core.money import format_inr
from app.core.settings_resolver import effective_settings
from app.engine.approvals import not_superseded
from app.engine.needs import need_from_payload, question_for
from app.engine.privacy import close_text


@dataclass(frozen=True)
class TimelineStep:
    at: datetime
    stage: str
    title: str
    text: str


# Case-level audit events -> (stage, title key, text key). Events not listed are not shown.
_CASE_EVENTS = {
    "case.awaiting_info": ("awaiting_info", "tl.question.title", "tl.question.text"),
    "case.info_added": ("investigating", "tl.replied.title", "tl.replied.text"),
    "case.escalate": ("escalated", "tl.passed.title", "status.escalated_team"),
    "case.escalated": ("escalated", "tl.passed.title", "status.escalated_team"),
    "case.closed": ("closed", "tl.closed.title", ""),  # text from the reason (S7.6)
    "case.apology": ("closed", "tl.noted.title", "status.apology_closed"),
}


def _remedy(proposal: ActionProposal, lang: str) -> str:
    amount = proposal.amount_paise
    key = f"remedy.{proposal.action}"
    label = proposal.action.replace("_", " ")
    if amount and key in TEMPLATES:
        return t(key, lang, amount=format_inr(amount))
    if amount:  # an action without its own wording still states its amount
        return t("remedy.other_amount", lang, label=label, amount=format_inr(amount))
    return t("remedy.other", lang, label=label)


def case_timeline(
    session: Session, case: Case, now: datetime | None = None, language: str | None = None
) -> list[TimelineStep]:
    """Oldest first, in `language` (default: the customer's own choice). The caller has
    already checked the case is visible to them."""
    now = now or datetime.now(UTC)
    lang = language or case_language(session, case)
    steps = [
        TimelineStep(
            case.opened_at,
            "received",
            t("tl.received.title", lang),
            t("tl.received.text", lang),
        ),
        TimelineStep(
            case.opened_at,
            "investigating",
            t("tl.looking.title", lang),
            t("tl.looking.text", lang),
        ),
    ]
    events = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "case",
            AuditEvent.entity_id == case.id,
            AuditEvent.event.in_(list(_CASE_EVENTS)),
        )
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
    )
    for e in events:
        stage, title_key, text_key = _CASE_EVENTS[e.event]
        if e.event == "case.closed":  # the reason is a code; the wording is ours
            reason = e.payload.get("reason")
            if f"close.{reason}" not in TEMPLATES:
                continue
            text_key = f"close.{reason}"
        text = t(text_key, lang)
        if e.event == "case.closed":  # the no-remedy wording carries the contact (M2)
            text = close_text(reason, effective_settings(session), lang)
        if e.event == "case.awaiting_info":  # say WHAT we need: a code-owned template
            text = question_for(need_from_payload(e.payload), lang)
        steps.append(TimelineStep(e.occurred_at, stage, t(title_key, lang), text))

    # Staff replies (S7.6): the template text as sent, and any note under its own label.
    for msg in session.scalars(
        select(TicketMessage)
        .join(Ticket, Ticket.id == TicketMessage.ticket_id)
        .where(Ticket.case_id == case.id, TicketMessage.author == "staff")
        .order_by(TicketMessage.sent_at, TicketMessage.id)
    ):
        title_key = "tl.staff_note.title" if msg.kind == "note" else "tl.staff.title"
        steps.append(TimelineStep(msg.sent_at, "investigating", t(title_key, lang), msg.body))

    proposals = session.scalars(
        select(ActionProposal)
        # A remedy an approver switched away from never happened as far as the customer is told.
        .where(ActionProposal.case_id == case.id, not_superseded())
        .order_by(ActionProposal.created_at, ActionProposal.id)
    )
    for proposal in proposals:
        # A proposal's steps are causal (proposed → approved → executed), but their stamps
        # come from two clocks: created_at from the database, decided_at/expires_at from the
        # app server. A server clock a second behind would sort "Approved" before "Proposed";
        # never let a step in the chain go back in time.
        chain = _proposal_steps(session, proposal, now, lang)
        for i in range(1, len(chain)):
            chain[i] = replace(chain[i], at=max(chain[i].at, chain[i - 1].at))
        steps += chain
    # Server-default stamps (transaction start) can be a hair before opened_at (set in Python
    # in the same transaction): nothing is shown before "received". The sort is stable, so
    # steps with the same time keep the order they were built in.
    clamped = [replace(s, at=max(s.at, case.opened_at)) for s in steps]
    return sorted(clamped, key=lambda s: s.at)


def _proposal_steps(
    session: Session, proposal: ActionProposal, now: datetime, lang: str = "en"
) -> list[TimelineStep]:
    steps = [
        TimelineStep(
            proposal.created_at,
            "awaiting_approval",
            t("tl.proposed.title", lang),
            t("tl.proposed.text", lang, remedy=_remedy(proposal, lang)),
        )
    ]
    approval = session.scalar(select(Approval).where(Approval.proposal_id == proposal.id))
    if approval is None:
        return steps
    if approval.decision == "rejected":
        steps.append(
            TimelineStep(
                approval.decided_at,
                "declined",
                t("tl.declined.title", lang),
                t("status.declined", lang),
            )
        )
        return steps
    steps.append(
        TimelineStep(
            approval.decided_at,
            "processing",
            t("tl.approved.title", lang),
            t("tl.approved.auto" if approval.mode == "auto" else "tl.approved.team", lang),
        )
    )
    if proposal.action == "free_item_voucher":
        return steps + _voucher_steps(session, proposal, approval, now, lang)
    if proposal.action != "refund":
        return steps
    execution = session.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
    ledger = session.scalar(
        select(RefundOperation).where(RefundOperation.proposal_id == proposal.id)
    )
    if execution is not None and execution.status == "succeeded":
        steps.append(
            TimelineStep(
                execution.updated_at,
                "confirmed",
                t("tl.refund_confirmed.title", lang),
                t("status.refund_confirmed", lang, amount=format_inr(proposal.amount_paise)),
            )
        )
    elif execution is not None and execution.status == "failed":
        steps.append(
            TimelineStep(
                execution.updated_at,
                "escalated",
                t("tl.passed.title", lang),
                t("status.refund_failed", lang),
            )
        )
    elif execution is None and now >= approval.expires_at:  # same rule as case_status
        steps.append(
            TimelineStep(
                approval.expires_at,
                "escalated",
                t("tl.passed.title", lang),
                t("tl.refund_check.text", lang),
            )
        )
    elif ledger is not None and ledger.status == "pending_reconciliation":
        steps.append(
            TimelineStep(
                ledger.updated_at,
                "escalated",
                t("tl.passed.title", lang),
                t("tl.refund_check.text", lang),
            )
        )
    return steps


def _voucher_steps(
    session: Session, proposal: ActionProposal, approval: Approval, now: datetime, lang: str = "en"
) -> list[TimelineStep]:
    """Same wording and rules as case_status: issued only once the voucher provider confirmed."""
    execution = session.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
    if execution is not None and execution.status == "succeeded":
        return [
            TimelineStep(
                execution.updated_at,
                "confirmed",
                t("tl.voucher_issued.title", lang),
                t("status.voucher_issued", lang, amount=format_inr(proposal.amount_paise)),
            )
        ]
    if execution is not None and execution.status == "failed":
        return [
            TimelineStep(
                execution.updated_at,
                "escalated",
                t("tl.passed.title", lang),
                t("status.voucher_failed", lang),
            )
        ]
    if execution is None and now >= approval.expires_at:  # same rule as case_status
        return [
            TimelineStep(
                approval.expires_at,
                "escalated",
                t("tl.passed.title", lang),
                t("tl.voucher_check.text", lang),
            )
        ]
    return []
