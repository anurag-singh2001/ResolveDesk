"""What the customer and staff are shown about an "ask the customer" question (S8.10).

Customer text comes only from templates in the case language (hard rule 7); amounts come from the
stored offer, which code computed from the rules. Nothing here promises a payment.
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.i18n import case_language, t
from app.core.models import Case, ProposalOffer
from app.core.money import format_inr
from app.engine.ask_customer import current_offer, proposal_is_pending
from app.engine.offer_state import is_expired, is_open, offer_for_proposal


def _kind(action: str) -> str:
    return "refund" if action == "refund" else "voucher"


def _days_left(offer: ProposalOffer, now: datetime) -> int:
    return max(1, -(-int((offer.expires_at - now).total_seconds()) // 86400))


def customer_offer(session: Session, case: Case, now: datetime) -> dict:
    """The customer's view. state: none | open | chosen | expired. Options only while open."""
    lang = case_language(session, case)
    none = {"state": "none", "heading": "", "intro": "", "expires_note": "", "options": []}
    offer = current_offer(session, case.id)
    if offer is None:
        return none
    # chosen: shown while the follow-up proposal is still waiting for a person.
    live_id = offer.new_proposal_id or offer.proposal_id
    if not proposal_is_pending(session, live_id):
        return none
    if is_open(offer, now):
        options = []
        for o in offer.options:
            kind = _kind(o["action"])
            options.append(
                {
                    "code": o["code"],
                    "kind": kind,
                    "title": t(f"option.{kind}.title", lang),
                    "summary": t(
                        f"option.{kind}.summary", lang, amount=format_inr(o["amount_paise"])
                    ),
                    "amount_paise": o["amount_paise"],
                    "approval": "team",  # a person always reviews what the customer picked
                    "timing": t("option.timing.team", lang),
                }
            )
        days = _days_left(offer, now)
        return {
            "state": "open",
            "heading": t("offer.heading", lang),
            "intro": t("offer.intro", lang),
            "expires_note": t("offer.expires", lang, days=days),
            "options": options,
            "expires_at": offer.expires_at,
            "status_text": t("offer.status.waiting", lang),
        }
    if offer.closed_reason is not None:
        return {**none, "state": "review", "status_text": t("offer.status.review", lang)}
    if offer.chosen_code is not None:
        return {**none, "state": "chosen", "status_text": t("offer.status.chosen", lang)}
    if is_expired(offer, now):
        return {**none, "state": "expired", "status_text": t("offer.status.expired", lang)}
    return none


def staff_offer(session: Session, proposal_id: uuid.UUID, now: datetime) -> dict | None:
    """For the approver: the question on this proposal (open or timed out), in English."""
    offer = offer_for_proposal(session, proposal_id)
    if offer is None:
        return None
    state = "open" if is_open(offer, now) else "expired"
    return {
        "state": state,
        "asked_at": offer.asked_at,
        "expires_at": offer.expires_at,
        "options": [
            {"code": o["code"], "kind": _kind(o["action"]), "amount_paise": o["amount_paise"]}
            for o in offer.options
        ],
    }
