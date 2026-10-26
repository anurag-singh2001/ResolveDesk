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

from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Execution,
    RefundOperation,
)
from app.core.money import format_inr


@dataclass(frozen=True)
class TimelineStep:
    at: datetime
    stage: str
    title: str
    text: str


# Case-level audit events -> (stage, title, text). Events not listed are not shown.
_CASE_EVENTS = {
    "case.awaiting_info": (
        "awaiting_info",
        "Question for you",
        "We asked you for a few more details about this order.",
    ),
    "case.escalate": (
        "escalated",
        "Passed to our team",
        "A member of our team will look into this.",
    ),
    "case.escalated": (
        "escalated",
        "Passed to our team",
        "A member of our team will look into this.",
    ),
    "case.apology": ("closed", "Noted", "Sorry about this. We have noted it with the team."),
}


def _remedy(proposal: ActionProposal) -> str:
    label = proposal.action.replace("_", " ")
    amount = proposal.amount_paise
    return f"a {label} of {format_inr(amount)}" if amount else f"a {label}"


def case_timeline(session: Session, case: Case, now: datetime | None = None) -> list[TimelineStep]:
    """Oldest first. The caller has already checked the case is visible to them."""
    now = now or datetime.now(UTC)
    steps = [
        TimelineStep(case.opened_at, "received", "Report received", "We received your report."),
        TimelineStep(
            case.opened_at,
            "investigating",
            "Looking into it",
            "We started looking into your order.",
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
    steps += [TimelineStep(e.occurred_at, *_CASE_EVENTS[e.event]) for e in events]

    proposals = session.scalars(
        select(ActionProposal)
        .where(ActionProposal.case_id == case.id)
        .order_by(ActionProposal.created_at, ActionProposal.id)
    )
    for proposal in proposals:
        steps += _proposal_steps(session, proposal, now)
    # Server-default stamps (transaction start) can be a hair before opened_at (set in Python
    # in the same transaction): nothing is shown before "received". The sort is stable, so
    # steps with the same time keep the order they were built in.
    clamped = [replace(s, at=max(s.at, case.opened_at)) for s in steps]
    return sorted(clamped, key=lambda s: s.at)


def _proposal_steps(
    session: Session, proposal: ActionProposal, now: datetime
) -> list[TimelineStep]:
    steps = [
        TimelineStep(
            proposal.created_at,
            "awaiting_approval",
            "Remedy proposed",
            f"We proposed {_remedy(proposal)}.",
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
                "Not approved",
                "Your request was reviewed and not approved.",
            )
        )
        return steps
    steps.append(
        TimelineStep(
            approval.decided_at,
            "processing",
            "Approved",
            "Approved automatically under the business's rules."
            if approval.mode == "auto"
            else "Your request was approved by our team.",
        )
    )
    if proposal.action == "free_item_voucher":
        return steps + _voucher_steps(session, proposal, approval, now)
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
                "Refund confirmed",
                f"Your refund of {format_inr(proposal.amount_paise)} has been processed by "
                "our payment provider.",
            )
        )
    elif execution is not None and execution.status == "failed":
        steps.append(
            TimelineStep(
                execution.updated_at,
                "escalated",
                "Passed to our team",
                "We could not complete the refund automatically. "
                "A member of our team will contact you.",
            )
        )
    elif execution is None and now >= approval.expires_at:  # same rule as case_status
        steps.append(
            TimelineStep(
                approval.expires_at,
                "escalated",
                "Passed to our team",
                "Your refund needs a check by our team before it can continue.",
            )
        )
    elif ledger is not None and ledger.status == "pending_reconciliation":
        steps.append(
            TimelineStep(
                ledger.updated_at,
                "escalated",
                "Passed to our team",
                "Your refund needs a check by our team before it can continue.",
            )
        )
    return steps


def _voucher_steps(
    session: Session, proposal: ActionProposal, approval: Approval, now: datetime
) -> list[TimelineStep]:
    """Same wording and rules as case_status: issued only once the voucher provider confirmed."""
    execution = session.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
    if execution is not None and execution.status == "succeeded":
        return [
            TimelineStep(
                execution.updated_at,
                "confirmed",
                "Voucher issued",
                f"Your voucher worth {format_inr(proposal.amount_paise)} has been issued.",
            )
        ]
    if execution is not None and execution.status == "failed":
        return [
            TimelineStep(
                execution.updated_at,
                "escalated",
                "Passed to our team",
                "We could not issue the voucher automatically. "
                "A member of our team will contact you.",
            )
        ]
    if execution is None and now >= approval.expires_at:  # same rule as case_status
        return [
            TimelineStep(
                approval.expires_at,
                "escalated",
                "Passed to our team",
                "Your voucher needs a check by our team before it can be issued.",
            )
        ]
    return []
