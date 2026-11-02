"""An approver switches a pending proposal to another remedy (S7.10).

The approver looks at a proposal (say a voucher) and sees the fair remedy is something else (a
partial refund, a smaller voucher). Instead of rejecting and starting over, they switch it:

- the old proposal is *superseded*: a `proposal_supersessions` row links it to the new one (a
  proposal itself is immutable, so it is never edited). A superseded proposal can't be decided
  or executed any more, and its customer-visible trace disappears: the customer only ever sees
  the final, verified outcome of the new proposal;
- the new proposal is made through `create_proposal` and `action.validate`, the same code
  checks as any proposal (caps, voucher <= order total, refund limits, needs_hq). It has its
  own payload hash, so an approval of the old hash can never execute it (hard rule 6);
- the switcher is the AUTHOR of the new proposal (`proposed_by`), so the four-eyes rule in
  `approvals.decide` applies to them: they cannot approve it. Two narrow exceptions, both
  audited with `self_approved: true` (owner decision M3, 2026-10-31):
    * a downgrade (a smaller amount of the same action, or a refund switched to a voucher not
      worth more): it cannot cost the business more than what was already proposed;
    * an hq_owner override, up to the setting `switch_self_approve_max_paise` (Rs 500), with a
      written reason, for a back office with no second person.
  Anything else waits for a different eligible person ("second_person") or, above the
  caller's escalation limit, for an hq_owner. Staff proposals are never auto-approved;
- everything runs under the case row lock that `approvals.decide` also takes, so approving the
  old proposal and switching it at the same moment have exactly one winner.

Amounts are integer paise and every value from the client is only a request.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.base import AmountRange, enabled_actions
from app.core import audit, events
from app.core.models import ActionProposal, Approval, ProposalSupersession
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.engine.approvals import (
    AlreadyDecided,
    Forbidden,
    NotEligible,
    NotFound,
    WaitingForCustomer,
    _order_id,
    decide,
    evaluate_proposal,
    is_superseded,
    lock_case,
    scoped_proposal,
)
from app.engine.eligibility import order_facts
from app.engine.offer_state import open_offer
from app.engine.privacy import PRIVACY_CATEGORY
from app.engine.proposals import ProposalError, create_proposal, proposal_hash_is_intact
from app.engine.routing import _lowest_user, case_brand

SWITCH_REASON_MAX = 500


@dataclass(frozen=True)
class Alternative:
    action: str
    min_paise: int
    max_paise: int
    step_paise: int
    needs_hq_above_paise: int | None  # above this only an hq_owner may approve
    you_can_approve_up_to_paise: int  # for the caller's role


@dataclass(frozen=True)
class SwitchResult:
    old_proposal_id: uuid.UUID
    proposal: ActionProposal
    approval: Approval | None
    waiting_for: str | None  # "hq_owner" (above the caller's limit) or "second_person"
    checks: dict
    self_approved: str | None = None  # "downgrade" | "owner_override" when the author approved


def is_downgrade(old: ActionProposal, new: ActionProposal, caller: uuid.UUID) -> bool:
    """The new remedy cannot cost more than the old one: the same action for a smaller amount,
    or a refund (cash) switched to a voucher worth no more. Anything else is an upgrade.

    The baseline must be somebody else's proposal. If the caller authored `old` (their own
    earlier switch, or a proposal they made), cutting it proves nothing: a person could raise
    an amount, wait, then "downgrade" their own raise and approve it alone. A proposal's
    author is never the engine's None, so `old` is the nearest proposal in the chain not
    authored by the caller exactly when `old.proposed_by != caller`; otherwise there is none
    and this is not a downgrade."""
    if old.proposed_by == caller:
        return False
    if old.amount_paise is None or new.amount_paise is None:
        return False
    if new.action == old.action:
        return new.amount_paise < old.amount_paise
    return (
        old.action == "refund" and new.action != "refund" and new.amount_paise <= old.amount_paise
    )


def _is_switchable_shape(action_cls) -> bool:
    """Only actions whose whole input is (order, amount, reason) can be built from a bare
    amount; anything richer needs its own form and is not offered here."""
    return bool(action_cls.amount_field) and set(action_cls.Input.model_fields) == {
        "transaction_id",
        action_cls.amount_field,
        "reason",
    }


def _pending_proposal(session: Session, ctx: TenantContext, proposal_id: uuid.UUID):
    """Scoped (404 otherwise), then locked and still undecided (409 otherwise)."""
    proposal = scoped_proposal(session, ctx, proposal_id)
    case = lock_case(session, proposal.case_id)
    if case is None:
        raise NotFound("proposal not found")
    decided = session.scalar(select(Approval.id).where(Approval.proposal_id == proposal.id))
    if decided is not None or is_superseded(session, proposal.id):
        raise AlreadyDecided("this proposal is no longer pending")
    if not proposal_hash_is_intact(proposal):
        raise NotEligible(["proposal no longer matches its payload hash"])
    return proposal, case


def _ranges(
    session: Session, proposal: ActionProposal, case
) -> dict[str, tuple[type, AmountRange]]:
    """The remedies the rules allow for this case, with the amounts each allows now."""
    order_id = _order_id(session, proposal)
    if order_id is None or case.category == PRIVACY_CATEGORY:
        return {}
    _, facts = order_facts(session, order_id, exclude_proposal=proposal.id)
    out = {}
    for name, cls in enabled_actions(tenant_pack(session).actions).items():
        if not (cls.counts_as_grant and _is_switchable_shape(cls)):
            continue
        rng = cls().amount_range(facts)
        if rng is not None:
            out[name] = (cls, rng)
    return out


def alternatives(
    session: Session, ctx: TenantContext, proposal_id: uuid.UUID
) -> tuple[ActionProposal, list[Alternative]]:
    proposal, case = _pending_proposal(session, ctx, proposal_id)
    out = []
    for name, (_, rng) in _ranges(session, proposal, case).items():
        up_to = rng.max_paise
        if rng.hq_above_paise is not None and ctx.role != "hq_owner":
            up_to = min(up_to, rng.hq_above_paise)
        out.append(
            Alternative(
                name, rng.min_paise, rng.max_paise, rng.step_paise, rng.hq_above_paise, up_to
            )
        )
    return proposal, out


def switch_remedy(
    session: Session,
    ctx: TenantContext,
    proposal_id: uuid.UUID,
    *,
    action: str,
    amount_paise: int | None,
    approve: bool,
    note: str,
    now: datetime,
    self_approve_reason: str | None = None,
) -> SwitchResult:
    """Raises NotFound (404: out of scope, other tenant), AlreadyDecided (409: not pending),
    Forbidden (403: an override asked for by someone who is not an hq_owner), NotEligible (422:
    not an allowed remedy, amount outside the rule's range, a missing reason, or a code check
    failed)."""
    old, case = _pending_proposal(session, ctx, proposal_id)
    if open_offer(session, old.id, now) is not None:
        raise WaitingForCustomer("waiting for the customer to choose")
    override = (self_approve_reason or "").strip()[:SWITCH_REASON_MAX]
    if self_approve_reason is not None:
        if not override:
            raise NotEligible(["say why you are approving it yourself (it is audited)"])
        if not approve:
            raise NotEligible(["approving it yourself needs approve to be true"])
        if ctx.role != "hq_owner":
            raise Forbidden("only an hq_owner may approve a switched remedy themselves")
    options = _ranges(session, old, case)
    if action not in options:
        raise NotEligible([f"{action} is not an allowed remedy for this case"])
    action_cls, rng = options[action]
    if type(amount_paise) is not int:  # also rejects bool and floats
        raise NotEligible(["amount_paise must be a whole number of paise"])
    if not rng.min_paise <= amount_paise <= rng.max_paise:
        raise NotEligible(
            [f"amount must be between {rng.min_paise} and {rng.max_paise} paise for {action}"]
        )
    if (amount_paise - rng.min_paise) % rng.step_paise:
        raise NotEligible([f"amount must be a multiple of {rng.step_paise} paise for {action}"])
    if action == old.action and amount_paise == old.amount_paise:
        raise NotEligible(["this is already the proposed remedy"])
    why = (note or "").strip()[:SWITCH_REASON_MAX]
    if not why:
        raise NotEligible(["say why you are switching (it is saved in the audit trail)"])
    reason = f"approver switched {old.action} to {action}" + (f": {why}" if why else "")

    params = {
        "transaction_id": str(_order_id(session, old)),
        action_cls.amount_field: amount_paise,
        "reason": reason[:SWITCH_REASON_MAX],
    }
    # Same path and same code checks as any proposal. Inside a savepoint so a refused one
    # leaves nothing behind.
    nested = session.begin_nested()
    try:
        new = create_proposal(
            session, ctx.tenant_id, case_id=case.id, action=action, params=params, reason=reason,
            basis=[{"code": "approver_set", "params": {}}],
            proposed_by=ctx.user_id,  # the switcher authors it: four-eyes applies to them
        )  # fmt: skip
        _, _, facts, result = evaluate_proposal(session, ctx, new, now)
        if not result.ok:
            raise NotEligible(result.errors)
    except ProposalError as exc:
        nested.rollback()
        raise NotEligible([str(exc)]) from None
    except NotEligible:
        nested.rollback()
        raise
    nested.commit()

    # Who may approve the new proposal in this same step. Its author (the caller) may not,
    # except for a downgrade or a small hq_owner override; otherwise it waits.
    needs_hq_hand = bool(result.checks.get("needs_hq")) and ctx.role != "hq_owner"
    self_basis, waiting = None, None
    if approve:
        limit = facts.settings.get("switch_self_approve_max_paise", 0)
        if needs_hq_hand:
            waiting = "hq_owner"  # created, not approved: the limit check stays what it was
        elif is_downgrade(old, new, ctx.user_id):
            self_basis = "downgrade"
        elif override and new.amount_paise is not None and new.amount_paise <= limit:
            self_basis = "owner_override"
        else:
            waiting = "second_person"  # an override above the limit also lands here, never silently

    session.add(
        ProposalSupersession(
            tenant_id=ctx.tenant_id,
            old_proposal_id=old.id,
            new_proposal_id=new.id,
            switched_by=ctx.user_id,
            reason=why or "no reason given",
        )
    )
    session.flush()
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="proposal.superseded",
        entity_type="proposal",
        entity_id=old.id,
        payload={
            "old_proposal_id": str(old.id),
            "new_proposal_id": str(new.id),
            "old_action": old.action,
            "old_amount_paise": old.amount_paise,
            "new_action": new.action,
            "new_amount_paise": new.amount_paise,
            # Not called "note": audit redacts that key, and the why is the point of this event.
            "switch_reason": why or None,
            "checks": result.checks,
            "self_approved": self_basis is not None,
            "self_approval_basis": self_basis,
            "self_approval_requested": bool(override),
            "override_reason": override or None if self_basis == "owner_override" else None,
        },
    )
    events.emit(
        session,
        ctx.tenant_id,
        "case.proposed",
        case.id,
        {"proposal_id": str(new.id), "auto_approved": False, "supersedes": str(old.id)},
    )
    if needs_hq_hand:
        _hand_to_hq(session, ctx, case, now)  # an hq_owner deciding it needs no hand-over

    approval = None
    if self_basis is not None:
        reason_text = override if self_basis == "owner_override" else why
        approval = decide(
            session, ctx, new.id, "approved", now, reason_text or None, self_approved=self_basis
        )
    return SwitchResult(old.id, new, approval, waiting, result.checks, self_basis)


def _hand_to_hq(session: Session, ctx: TenantContext, case, now: datetime) -> None:
    """The new amount is above what an outlet may decide: the case is owned by HQ (S7.2)."""
    owner = _lowest_user(session, "hq_owner", None, case_brand(session, case))
    if owner is None or owner == case.owner_user_id:
        return
    previous = case.owner_user_id
    case.owner_user_id = owner
    case.owner_assigned_at = now
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="system",
        actor_id=None,
        event="case.owner_assigned",
        entity_type="case",
        entity_id=case.id,
        payload={
            "owner_user_id": str(owner),
            "previous_owner_user_id": str(previous) if previous else None,
            "auto": True,
            "why": "remedy switched above the outlet limit",
        },
    )
