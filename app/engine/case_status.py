"""What a customer may be told about their case (hard rule 7).

Only states a tool confirmed are stated. "Confirmed" requires the provider to have reported
success AND the verifier to have re-read it from the provider by key and found it matching; a
timeout is "still processing", never success; a decision is not the same as money having moved.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import case_language, t
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Execution,
    RefundOperation,
    Verification,
)
from app.core.money import format_inr
from app.core.settings_resolver import effective_settings
from app.engine.approvals import not_superseded
from app.engine.needs import latest_question
from app.engine.privacy import PRIVACY_CATEGORY, close_text, customer_message

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


def is_payout_confirmed(action: str, execution: Execution | None, verification: str | None) -> bool:
    """The one definition of "this payout is confirmed" (also used to decide a case may be
    closed): the provider reported success and, for a refund, the verifier matched it."""
    return (
        execution is not None
        and execution.status == "succeeded"
        and (action != "refund" or verification == "verified")
    )


def case_status(
    session: Session, case: Case, now: datetime | None = None, language: str | None = None
) -> CaseStatus:
    """The customer-safe status, in `language` (default: the customer's own choice)."""
    now = now or datetime.now(UTC)
    lang = language or case_language(session, case)
    proposal = session.scalars(
        select(ActionProposal)
        .where(ActionProposal.case_id == case.id, not_superseded())
        .order_by(ActionProposal.created_at.desc())
    ).first()
    if proposal is None:
        if case.close_reason:  # a person closed it with a reason (S7.6)
            return CaseStatus(
                "closed", close_text(case.close_reason, effective_settings(session), lang)
            )
        if case.status == "escalated" and case.category == PRIVACY_CATEGORY:
            return CaseStatus(
                "escalated", customer_message(case.opened_at, effective_settings(session), lang)
            )
        if case.status == "escalated":
            return CaseStatus("escalated", t("status.escalated_team", lang))
        if case.status == "awaiting_info":
            return CaseStatus(
                "awaiting_info",
                t("status.need_info", lang) + " " + latest_question(session, case.id, lang),
            )
        if case.status == "resolved":
            return CaseStatus("closed", t("status.apology_closed", lang))
        return CaseStatus("investigating", t("status.investigating", lang))

    amount = proposal.amount_paise
    common = {"action": proposal.action, "amount_paise": amount, "proposal_id": str(proposal.id)}
    approval = session.scalar(select(Approval).where(Approval.proposal_id == proposal.id))
    if approval is None:
        return CaseStatus("awaiting_approval", t("status.awaiting_approval", lang), **common)
    if approval.decision == "rejected":
        return CaseStatus("declined", t("status.declined", lang), **common)
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
    # The provider confirmed this payout (a refund also re-read and matched by the verifier).
    payout_confirmed = is_payout_confirmed(proposal.action, execution, verification)
    if (
        case.status == "escalated"
        and not payout_confirmed
        and (execution is None or execution.status != "failed")
    ):
        # Approved, but the engine handed it to a person (e.g. the approval expired before
        # execution, or the provider's record didn't match ours). A confirmed payout is still
        # reported as confirmed: the case may be escalated for another reason (say, a second
        # proposal on it was refused), and the money that moved is a verified fact.
        return CaseStatus("escalated", t("status.needs_check_any", lang), **common)
    if proposal.action == "free_item_voucher":
        return _voucher_status(execution, approval, now, amount, common, lang)
    if proposal.action != "refund":
        # No executor for this action yet: approved, not yet done.
        return CaseStatus("processing", t("status.approved_pending", lang), **common)
    if verification == "mismatch":  # the provider's record disagrees with ours
        return CaseStatus("escalated", t("status.needs_check_refund", lang), **common)
    if execution is not None and execution.status == "succeeded" and verification == "verified":
        return CaseStatus(
            "confirmed",
            t("status.refund_confirmed", lang, amount=format_inr(amount)),
            **common,
        )
    ledger = session.scalar(
        select(RefundOperation.status).where(RefundOperation.proposal_id == proposal.id)
    )
    stuck = (execution is None and now >= approval.expires_at) or (
        ledger == "pending_reconciliation"
    )
    if stuck:  # approved, but not moving: say so instead of "being processed"
        return CaseStatus("escalated", t("status.needs_check_refund", lang), **common)
    if execution is not None and execution.status == "failed":
        if verification != "verified":
            return CaseStatus("escalated", t("status.needs_check_refund", lang), **common)
        return CaseStatus("escalated", t("status.refund_failed", lang), **common)
    return CaseStatus(
        "processing",
        t("status.refund_processing", lang, amount=format_inr(amount)),
        **common,
    )


def _voucher_status(execution, approval, now, amount, common, lang) -> CaseStatus:
    """Issued only when the voucher provider confirmed it; a timeout is still processing."""
    status = execution.status if execution is not None else None
    if status == "succeeded":
        return CaseStatus(
            "confirmed", t("status.voucher_issued", lang, amount=format_inr(amount)), **common
        )
    if status == "failed":
        return CaseStatus(
            "escalated",
            t("status.voucher_failed", lang),
            **common,
        )
    if now >= approval.expires_at:  # approved long ago and still not issued: not moving
        return CaseStatus(
            "escalated",
            t("status.voucher_needs_check", lang),
            **common,
        )
    return CaseStatus(
        "processing",
        t("status.voucher_processing", lang, amount=format_inr(amount)),
        **common,
    )
