"""Staff decide a case that needs a person (S7.5): set its category, propose a remedy.

A staff proposal goes through the SAME path as an engine one: create_proposal (strict params,
hash) -> the action's own code checks (caps, refundable balance, voucher <= order total) ->
lifecycle.proposal_made (tenant auto-approve rule, else a human approval that is hash-bound
and expires) -> executor -> verifier. Staff never write money directly.

What staff may pick comes from the vertical pack, not from this module: the category's rule in
`remedies` says which actions fit, and tenant settings give the amount ceiling. The numbers the
browser sends are proposals, checked here again in code (hard rule 8).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.base import enabled_actions
from app.core import audit
from app.core.models import ActionProposal, Approval, Case, Ticket
from app.core.money import format_inr, percent_of
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext
from app.core.verticals import RefundPercentOption, rule_options
from app.engine import lifecycle
from app.engine.approvals import evaluate_proposal
from app.engine.eligibility import order_facts
from app.engine.privacy import PRIVACY_CATEGORY
from app.engine.proposals import ProposalError, create_proposal, parse_params, payload_hash
from app.engine.resolver import MIN_VOUCHER_PAISE, missing_items_paise
from app.engine.routing import assign_owner


# Which actions each option of a pack rule can lead to (a rule is one option or a list of them,
# S7.9). The late-delivery tiers pick by lateness for the AI; a person may choose either action,
# within the same ceilings. A refund_percent option is a refund.
def _option_actions(option) -> tuple[str, ...]:
    if option == "late_tiers":
        return ("free_item_voucher", "refund")
    if option == "refund_missing" or isinstance(option, RefundPercentOption):
        return ("refund",)
    return ("free_item_voucher",)


_RUPEE = 100


class StaffDecisionError(Exception):
    """Base. Subclasses map to HTTP 409 / 422 in the route."""


class NotNeedingPerson(StaffDecisionError):
    """The case is not waiting for a person (e.g. already proposed, executing, closed)."""


class InvalidChoice(StaffDecisionError):
    """The category, remedy or amount is outside the pack's rules; the message says why."""


@dataclass(frozen=True)
class RemedyOption:
    action: str
    min_paise: int
    max_paise: int


@dataclass(frozen=True)
class RemedyOptions:
    categories: list[str]
    category: str | None
    options: list[RemedyOption]
    note: str | None  # plain reason when there are no options for this case


@dataclass(frozen=True)
class Proposed:
    proposal: ActionProposal
    created: bool
    auto_approved: bool
    checks: dict = field(default_factory=dict)


def lock_case(session: Session, case_id: uuid.UUID) -> Case:
    return session.execute(
        select(Case)
        .where(Case.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def require_person_needed(session: Session, case: Case) -> None:
    """Only an escalated case is waiting for a person to decide it. A case with a pending
    proposal is waiting for an approver instead (the approvals queue)."""
    if case.status != "escalated":
        raise NotNeedingPerson("this case does not need a person to decide it")
    started = session.scalar(
        select(ActionProposal.id)
        .join(Approval, Approval.proposal_id == ActionProposal.id)
        .where(ActionProposal.case_id == case.id, Approval.decision == "approved")
        .limit(1)
    )
    if started is not None:  # escalated after a payout was approved: check that one first
        raise NotNeedingPerson("a payout was already approved for this case; check it first")


def remedy_options(session: Session, case: Case) -> RemedyOptions:
    """Category list and the remedies allowed now, with the amount range for this case."""
    pack = tenant_pack(session)
    category = case.category
    base = {"categories": list(pack.issue_categories), "category": category}
    if category is None:
        return RemedyOptions(**base, options=[], note="Choose a category first.")
    if category == PRIVACY_CATEGORY:
        return RemedyOptions(**base, options=[], note="Privacy requests never get a payout.")
    rule = pack.remedies.get(category)
    if rule is None:
        return RemedyOptions(**base, options=[], note="No remedy is set for this category.")
    if case.transaction_id is None:
        return RemedyOptions(**base, options=[], note="This case has no order to pay against.")
    order, facts = order_facts(session, case.transaction_id)
    s = facts.settings
    enabled = enabled_actions(pack.actions)
    ranges: dict[str, int] = {}  # action -> highest ceiling any option of the rule gives
    for option in rule_options(rule):
        for action in _option_actions(option):
            if action not in enabled:
                continue
            if action == "refund":
                if s["refund_channel"] != "tenant_gateway":
                    continue  # refunds for this order go through the aggregator
                cap = percent_of(order.total_paise, s["refund_max_percent"])
                top = min(cap, facts.refundable_paise)
                if option == "refund_missing":
                    top = min(top, missing_items_paise(session, order.id))
                if top >= 1:
                    ranges[action] = max(ranges.get(action, 0), top)
            else:
                scaled = percent_of(order.total_paise, s.get("voucher_percent", 100))
                top = min(s["voucher_max_paise"], scaled)
                top -= top % _RUPEE
                if top >= MIN_VOUCHER_PAISE:
                    ranges[action] = max(ranges.get(action, 0), top)
    options = [
        RemedyOption(a, 1 if a == "refund" else MIN_VOUCHER_PAISE, top) for a, top in ranges.items()
    ]
    note = None if options else "No remedy is available for this order right now."
    return RemedyOptions(**base, options=options, note=note)


def categorise(
    session: Session, ctx: TenantContext, case: Case, category: str, now: datetime
) -> Case:
    """Set the category of a case that needs a person. Audited with the previous value."""
    case = lock_case(session, case.id)
    require_person_needed(session, case)
    if category not in tenant_pack(session).issue_categories:
        raise InvalidChoice(f"unknown category {category!r}")
    previous = case.category
    if previous == category:
        return case  # idempotent: nothing changes, nothing new to audit
    case.category = category
    ticket = session.scalar(select(Ticket).where(Ticket.case_id == case.id))
    if ticket is not None:
        ticket.category = category
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.categorised_by_staff",
        entity_type="case",
        entity_id=case.id,
        payload={"category": category, "previous_category": previous},
    )
    return case


def propose(
    session: Session,
    ctx: TenantContext,
    case: Case,
    *,
    action: str,
    amount_paise: int | None,
    now: datetime,
) -> Proposed:
    """Create the proposal for a remedy the pack allows, then run it down the normal path.

    Repeating the same request returns the same proposal (idempotency key: case + payload
    hash, enforced by a unique index as well as the lookup below)."""
    case = lock_case(session, case.id)
    if case.category is None or case.transaction_id is None:
        require_person_needed(session, case)
        raise InvalidChoice("choose a category for this case first")
    reason = f"Chosen by staff for {case.category.replace('_', ' ')}"
    action_cls = enabled_actions(tenant_pack(session).actions).get(action)
    if action_cls is None or action_cls.amount_field is None:
        raise InvalidChoice("this remedy is not available")
    if amount_paise is None:
        raise InvalidChoice("an amount is required")
    params = {
        "transaction_id": str(case.transaction_id),
        action_cls.amount_field: amount_paise,
        "reason": reason,
    }
    try:
        normalised = parse_params(action_cls, params)
    except ProposalError as exc:
        raise InvalidChoice("the amount is not valid") from exc
    digest = payload_hash(action, case.id, normalised)
    existing = session.scalar(
        select(ActionProposal).where(
            ActionProposal.case_id == case.id,
            ActionProposal.payload_hash == digest,
            ActionProposal.proposed_by.is_not(None),
        )
    )
    if existing is not None:  # a retry or a double click: same proposal, nothing new
        approved = session.scalar(
            select(Approval.id).where(
                Approval.proposal_id == existing.id, Approval.decision == "approved"
            )
        )
        return Proposed(existing, False, approved is not None)
    require_person_needed(session, case)
    option = {o.action: o for o in remedy_options(session, case).options}.get(action)
    if option is None:
        raise InvalidChoice(f"{action.replace('_', ' ')} is not allowed for this category")
    if not option.min_paise <= amount_paise <= option.max_paise:
        raise InvalidChoice(
            f"the amount must be between {format_inr(option.min_paise)} "
            f"and {format_inr(option.max_paise)}"
        )
    try:
        proposal = create_proposal(
            session,
            ctx.tenant_id,
            case_id=case.id,
            action=action,
            params=normalised,
            reason=reason,
            proposed_by=ctx.user_id,
        )
    except ProposalError as exc:
        raise InvalidChoice(str(exc)) from exc
    _, _, _, result = evaluate_proposal(session, ctx, proposal, now)
    if not result.ok:  # the action's own checks, run again on the stored proposal
        raise InvalidChoice("; ".join(result.errors))
    approval = lifecycle.proposal_made(session, ctx.tenant_id, case, proposal.id, now)
    assign_owner(session, ctx.tenant_id, case, now)
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.proposed_by_staff",
        entity_type="case",
        entity_id=case.id,
        payload={
            "proposal_id": str(proposal.id),
            "action": action,
            "amount_paise": amount_paise,
            "proposed_by": str(ctx.user_id),
            "auto_approved": approval is not None,
        },
    )
    return Proposed(proposal, True, approval is not None, result.checks)
