"""Ask the customer to choose between two remedies, then review (S8.10).

The owner's flow: check the policy, ask the customer to pick one of two options, review the
answer, and only then act.

- An approver (staff in scope) offers exactly two remedies on a pending proposal. Both come from
  what the rule and policy allow right now: the same `amount_range` hooks as switching (a voucher
  up to min(voucher limit, order total), a refund up to the percent cap and the refundable
  balance; none for a delivery-app order). Amounts are integer paise and every client value is
  only a request.
- The proposal stays undecided and immutable. While the question is open, `approvals.decide`
  refuses to approve it. Nothing is paid and no money state changes.
- The customer's pick (an option code, checked against the stored offer, once) supersedes the old
  proposal with a NEW proposal built through `create_proposal` and the same code checks. It is
  never auto-approved: `proposed_by` is the staff member who asked, so four-eyes applies (they
  cannot approve it), and a person reviews it. Fair use stays a warning, never a refusal.
- No answer by the deadline: the proposal is an ordinary pending one for a person.
- Allergen, illness and foreign-object reports are never offered compensation instead of a manager
  review (fair-use policy 3.1), so asking is refused for them.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.base import AmountRange
from app.core import audit, events
from app.core.models import ActionProposal, Approval, Case, ProposalOffer, ProposalSupersession
from app.core.tenancy import TenantContext
from app.engine.approvals import (
    ApprovalError,
    NotEligible,
    NotFound,
    evaluate_proposal,
    is_superseded,
    lock_case,
)
from app.engine.case_messages import customer_messages
from app.engine.eligibility import order_facts
from app.engine.offer_state import is_open, offer_for_proposal
from app.engine.privacy import PRIVACY_CATEGORY
from app.engine.proposals import ProposalError, create_proposal
from app.engine.switch import _hand_to_hq, _order_id, _pending_proposal, _ranges

OFFERABLE = ("free_item_voucher", "refund")  # the two kinds a customer can read and choose
DEFAULT_ANSWER_DAYS = 3

# Words that mean an allergic reaction, illness or a foreign object (fair-use policy 3.1). A
# plain scan of what the customer wrote, in English, Hinglish and Devanagari. It errs on the side
# of refusing: a false match only means the case goes to a manager, which is where it belongs.
_SAFETY = re.compile(
    r"allerg|anaphyla|rash|swollen|swelling|vomit|nausea|food.?poison|\bsick\b|\bill\b|illness"
    r"|diarr|stomach|hospital|doctor|foreign|insect|cockroach|worm|\bhair\b|\bglass\b|\bstone\b"
    r"|plastic|metal|\bkeeda\b|\bkida\b|\bulti\b|\bbimar|\bbimaar|\btabiyat|\bbaal\b"
    r"|एलर्ज|उल्टी|बीमार|कीड़|कीडे|कांच|काँच|पत्थर|बाल",
    re.IGNORECASE,
)


class CannotAsk(ApprovalError):
    """Asking the customer is not allowed for this proposal; `reason` is safe to show staff."""

    code = "cannot_ask"

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class OfferClosed(ApprovalError):
    """The question is no longer open (answered, timed out, or the proposal was decided)."""

    code = "offer_closed"


class InvalidPick(ApprovalError):
    code = "invalid_pick"


@dataclass(frozen=True)
class OfferedOption:
    code: str
    action: str
    amount_paise: int

    def as_json(self) -> dict:
        return {"code": self.code, "action": self.action, "amount_paise": self.amount_paise}


def option_code(action: str, amount_paise: int) -> str:
    return f"{'refund' if action == 'refund' else 'voucher'}_{amount_paise}"


def is_safety_case(session: Session, case: Case) -> bool:
    return any(_SAFETY.search(text) for _, text in customer_messages(session, case.id))


def answer_days(session: Session, proposal: ActionProposal) -> int:
    order_id = _order_id(session, proposal)
    if order_id is None:
        return DEFAULT_ANSWER_DAYS
    _, facts = order_facts(session, order_id, exclude_proposal=proposal.id)
    value = facts.settings.get("customer_answer_days", DEFAULT_ANSWER_DAYS)
    return value if type(value) is int and value > 0 else DEFAULT_ANSWER_DAYS


def _offerable(session: Session, proposal: ActionProposal, case: Case) -> dict[str, AmountRange]:
    return {
        name: rng
        for name, (_, rng) in _ranges(session, proposal, case).items()
        if name in OFFERABLE
    }


def blocked_reason(session: Session, proposal: ActionProposal, case: Case) -> str | None:
    """Why this proposal can't be put to the customer, or None."""
    if case.category == PRIVACY_CATEGORY:
        return "Privacy requests never get a payout."
    if is_safety_case(session, case):
        return (
            "An allergy, illness or foreign-object report goes straight to a manager. The policy "
            "(fair use 3.1) says not to offer compensation in place of that review."
        )
    if len(_offerable(session, proposal, case)) < 1:
        return "The rules allow no voucher or refund for this order right now."
    return None


def suggestion(
    session: Session, ctx: TenantContext, proposal_id: uuid.UUID, now: datetime
) -> tuple[ActionProposal, list[OfferedOption], str | None, int]:
    """The default two options (a voucher and a partial refund, each at its maximum) when both
    are allowed, the reason asking is blocked (if so), and the answer window in days."""
    proposal, case = _pending_proposal(session, ctx, proposal_id)
    days = answer_days(session, proposal)
    existing = offer_for_proposal(session, proposal.id)
    if existing is not None:
        return proposal, [], "The customer was already asked about this proposal.", days
    reason = blocked_reason(session, proposal, case)
    if reason is not None:
        return proposal, [], reason, days
    ranges = _offerable(session, proposal, case)
    options = [
        OfferedOption(option_code(a, ranges[a].max_paise), a, ranges[a].max_paise)
        for a in OFFERABLE
        if a in ranges
    ]
    if len(options) < 2:
        return (
            proposal,
            options,
            "Only one kind of remedy is allowed here, so there is no choice to offer.",
            days,
        )
    return proposal, options, None, days


def _validate_request(requested: list[dict], ranges: dict[str, AmountRange]) -> list[OfferedOption]:
    if not isinstance(requested, list) or len(requested) != 2:
        raise NotEligible(["offer exactly two options"])
    out: list[OfferedOption] = []
    for item in requested:
        action = item.get("action")
        if action not in ranges:
            raise NotEligible([f"{action} is not an allowed remedy to offer for this case"])
        rng = ranges[action]
        amount = item.get("amount_paise")
        if amount is None:
            amount = rng.max_paise
        if type(amount) is not int:  # also rejects bool and floats
            raise NotEligible(["amount_paise must be a whole number of paise"])
        if not rng.min_paise <= amount <= rng.max_paise:
            raise NotEligible(
                [f"amount must be between {rng.min_paise} and {rng.max_paise} paise for {action}"]
            )
        if (amount - rng.min_paise) % rng.step_paise:
            raise NotEligible([f"amount must be a multiple of {rng.step_paise} paise for {action}"])
        out.append(OfferedOption(option_code(action, amount), action, amount))
    if out[0].code == out[1].code:
        raise NotEligible(["the two options must differ"])
    return out


def ask_customer(
    session: Session,
    ctx: TenantContext,
    proposal_id: uuid.UUID,
    requested: list[dict],
    now: datetime,
) -> ProposalOffer:
    """Raises NotFound (404: out of scope, other tenant), AlreadyDecided (409: not pending),
    CannotAsk (409: allergen/illness/privacy, already asked, nothing allowed), NotEligible (422:
    an option outside the rule)."""
    proposal, case = _pending_proposal(session, ctx, proposal_id)
    if offer_for_proposal(session, proposal.id) is not None:
        raise CannotAsk("The customer was already asked about this proposal.")
    reason = blocked_reason(session, proposal, case)
    if reason is not None:
        raise CannotAsk(reason)
    options = _validate_request(requested, _offerable(session, proposal, case))
    offer = ProposalOffer(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        proposal_id=proposal.id,
        case_id=case.id,
        asked_by=ctx.user_id,  # from the token, never from the request
        asked_at=now,
        expires_at=now + timedelta(days=answer_days(session, proposal)),
        options=[o.as_json() for o in options],
    )
    session.add(offer)
    session.flush()
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.options_offered",
        entity_type="case",
        entity_id=case.id,
        payload={
            "proposal_id": str(proposal.id),
            "options": [{"code": o.code, "amount_paise": o.amount_paise} for o in options],
        },
    )
    return offer


def current_offer(session: Session, case_id: uuid.UUID) -> ProposalOffer | None:
    return session.scalars(
        select(ProposalOffer)
        .where(ProposalOffer.case_id == case_id)
        .order_by(ProposalOffer.asked_at.desc(), ProposalOffer.id)
    ).first()


def proposal_is_pending(session: Session, proposal_id: uuid.UUID) -> bool:
    decided = session.scalar(select(Approval.id).where(Approval.proposal_id == proposal_id))
    return decided is None and not is_superseded(session, proposal_id)


def choose(
    session: Session, ctx: TenantContext, case_id: uuid.UUID, code: str, now: datetime
) -> ProposalOffer:
    """The customer's pick (the caller checked they own the case). Raises OfferClosed (409:
    nothing open, answered already, timed out, proposal decided), InvalidPick (422: not one of
    the stored options), NotEligible (422: the rule no longer allows it)."""
    case = lock_case(session, case_id)  # same lock as deciding and switching
    if case is None:
        raise NotFound("case not found")
    offer = current_offer(session, case.id)
    if offer is None or not is_open(offer, now):
        raise OfferClosed("there is no open question on this case")
    old = session.get(ActionProposal, offer.proposal_id)
    if old is None or not proposal_is_pending(session, old.id):
        raise OfferClosed("this case has already been decided")
    picked = next((o for o in offer.options if o["code"] == code), None)
    if picked is None:
        raise InvalidPick("that is not one of the options offered")
    action, amount = picked["action"], int(picked["amount_paise"])
    ranges = {n: r for n, (_, r) in _ranges(session, old, case).items() if n in OFFERABLE}
    cls_by_name = {n: c for n, (c, _) in _ranges(session, old, case).items()}
    if action not in ranges or not ranges[action].min_paise <= amount <= ranges[action].max_paise:
        raise NotEligible(["that option is no longer available"])
    params = {
        "transaction_id": str(_order_id(session, old)),
        cls_by_name[action].amount_field: amount,
        "reason": "customer chose this option when asked by a team member",
    }
    nested = session.begin_nested()
    try:
        new = create_proposal(
            session, ctx.tenant_id, case_id=case.id, action=action, params=params,
            reason="customer chose this option when asked by a team member",
            basis=[{"code": "customer_chose", "params": {}}],
            proposed_by=offer.asked_by,  # four-eyes: the asker can't approve it either
        )  # fmt: skip
        _, _, _, result = evaluate_proposal(session, ctx, new, now)
        if not result.ok:
            raise NotEligible(result.errors)
    except ProposalError as exc:
        nested.rollback()
        raise NotEligible([str(exc)]) from None
    except NotEligible:
        nested.rollback()
        raise
    nested.commit()
    session.add(
        ProposalSupersession(
            tenant_id=ctx.tenant_id,
            old_proposal_id=old.id,
            new_proposal_id=new.id,
            switched_by=offer.asked_by,
            reason="customer chose when asked",
        )
    )
    offer.chosen_code = code
    offer.chosen_at = now
    offer.new_proposal_id = new.id
    session.flush()
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.options_chosen",
        entity_type="case",
        entity_id=case.id,
        payload={
            "option": code,
            "amount_paise": amount,
            "old_proposal_id": str(old.id),
            "new_proposal_id": str(new.id),
        },
    )
    events.emit(
        session,
        ctx.tenant_id,
        "case.proposed",
        case.id,
        {"proposal_id": str(new.id), "auto_approved": False, "supersedes": str(old.id)},
    )
    if result.checks.get("needs_hq"):
        _hand_to_hq(session, ctx, case, now)
    return offer
