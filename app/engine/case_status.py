"""What a customer may be told about their case (hard rule 7).

Only states a tool confirmed are stated. "Confirmed" requires the provider to have reported
success; a timeout is "still processing", never success; a decision is not the same as money
having moved.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import ActionProposal, Approval, Case, Execution, RefundOperation
from app.core.money import format_inr

STAGES = (
    "received",
    "investigating",
    "awaiting_info",
    "awaiting_approval",
    "processing",
    "confirmed",
    "declined",
    "escalated",
    "closed",
)


@dataclass(frozen=True)
class CaseStatus:
    stage: str
    message: str
    action: str | None = None
    amount_paise: int | None = None
    proposal_id: str | None = None


def case_status(session: Session, case: Case, now: datetime | None = None) -> CaseStatus:
    now = now or datetime.now(UTC)
    proposal = session.scalars(
        select(ActionProposal)
        .where(ActionProposal.case_id == case.id)
        .order_by(ActionProposal.created_at.desc())
    ).first()
    if proposal is None:
        if case.status == "escalated":
            return CaseStatus("escalated", "A member of our team will look into this.")
        if case.status == "awaiting_info":
            return CaseStatus(
                "awaiting_info", "We need a little more information from you about this order."
            )
        if case.status == "resolved":
            return CaseStatus("closed", "Sorry about this. We have noted it with the team.")
        return CaseStatus("investigating", "We are looking into your order.")

    amount = proposal.amount_paise
    common = {"action": proposal.action, "amount_paise": amount, "proposal_id": str(proposal.id)}
    approval = session.scalar(select(Approval).where(Approval.proposal_id == proposal.id))
    if approval is None:
        return CaseStatus(
            "awaiting_approval", "Your request is waiting for a team member's approval.", **common
        )
    if approval.decision == "rejected":
        return CaseStatus("declined", "Your request was reviewed and not approved.", **common)
    execution = session.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
    if proposal.action == "free_item_voucher":
        return _voucher_status(execution, approval, now, amount, common)
    if proposal.action != "refund":
        # No executor for this action yet: approved, not yet done.
        return CaseStatus("processing", "Approved. We will confirm once it is ready.", **common)
    if execution is not None and execution.status == "succeeded":
        return CaseStatus(
            "confirmed",
            f"Your refund of {format_inr(amount)} has been processed by our payment provider.",
            **common,
        )
    ledger = session.scalar(
        select(RefundOperation.status).where(RefundOperation.proposal_id == proposal.id)
    )
    stuck = (execution is None and now >= approval.expires_at) or (
        ledger == "pending_reconciliation"
    )
    if stuck:  # approved, but not moving: say so instead of "being processed"
        return CaseStatus(
            "escalated",
            "Your refund needs a check by our team before it can continue. We will update you.",
            **common,
        )
    if execution is not None and execution.status == "failed":
        return CaseStatus(
            "escalated",
            "We could not complete the refund automatically. "
            "A member of our team will contact you.",
            **common,
        )
    return CaseStatus(
        "processing",
        f"Your refund of {format_inr(amount)} is approved and "
        "being processed. We will confirm once the payment provider does.",
        **common,
    )


def _voucher_status(execution, approval, now, amount, common) -> CaseStatus:
    """Issued only when the voucher provider confirmed it; a timeout is still processing."""
    status = execution.status if execution is not None else None
    if status == "succeeded":
        return CaseStatus(
            "confirmed", f"Your voucher worth {format_inr(amount)} has been issued.", **common
        )
    if status == "failed":
        return CaseStatus(
            "escalated",
            "We could not issue the voucher automatically. A member of our team will contact you.",
            **common,
        )
    if now >= approval.expires_at:  # approved long ago and still not issued: not moving
        return CaseStatus(
            "escalated",
            "Your voucher needs a check by our team before it can be issued. We will update you.",
            **common,
        )
    return CaseStatus(
        "processing",
        f"Your voucher worth {format_inr(amount)} is approved. "
        "We will confirm once it has been issued.",
        **common,
    )
