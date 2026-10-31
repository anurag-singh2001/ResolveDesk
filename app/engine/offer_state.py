"""Is a customer question open on this proposal? (S8.10)

Models only, so `approvals.decide` can import it without a cycle. A question is *open* while it
is unanswered and before its deadline. Open means nobody may approve the proposal: the person
who asked wants the customer's answer first. After the deadline the question is *expired* and the
proposal is an ordinary pending one again, for a person to decide.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import ProposalOffer

REASON_WAITING = "waiting"
REASON_CUSTOMER_CHOSE = "customer_chose"
REASON_NO_ANSWER = "no_customer_answer"


def offer_for_proposal(session: Session, proposal_id: uuid.UUID) -> ProposalOffer | None:
    return session.scalar(select(ProposalOffer).where(ProposalOffer.proposal_id == proposal_id))


def is_open(offer: ProposalOffer, now: datetime) -> bool:
    return offer.chosen_code is None and now < offer.expires_at


def is_expired(offer: ProposalOffer, now: datetime) -> bool:
    return offer.chosen_code is None and now >= offer.expires_at


def open_offer(session: Session, proposal_id: uuid.UUID, now: datetime) -> ProposalOffer | None:
    offer = offer_for_proposal(session, proposal_id)
    return offer if offer is not None and is_open(offer, now) else None


def queue_reasons(
    session: Session, proposal_ids: list[uuid.UUID], now: datetime
) -> dict[uuid.UUID, str]:
    """For still-pending proposals only: why a person sees (or does not yet see) each one.
    waiting: the customer is being asked, so the case is not in the queue yet.
    customer_chose: this proposal was created from the customer's pick.
    no_customer_answer: the question ran out of time with no answer."""
    if not proposal_ids:
        return {}
    out: dict[uuid.UUID, str] = {}
    rows = session.scalars(
        select(ProposalOffer).where(
            (ProposalOffer.proposal_id.in_(proposal_ids))
            | (ProposalOffer.new_proposal_id.in_(proposal_ids))
        )
    )
    for offer in rows:
        if offer.new_proposal_id in proposal_ids:
            out[offer.new_proposal_id] = REASON_CUSTOMER_CHOSE
        elif offer.proposal_id in proposal_ids:
            if is_open(offer, now):
                out[offer.proposal_id] = REASON_WAITING
            elif is_expired(offer, now):
                out[offer.proposal_id] = REASON_NO_ANSWER
    return out
