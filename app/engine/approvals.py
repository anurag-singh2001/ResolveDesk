"""Approval decisions and whether an approval may still be acted on (hard rule 6).

`decide` records a human decision; `auto_decide` applies a tenant's auto-approve rule (never
for refunds). `check_usable` is what the executor calls right before reserving money: the DB
already binds an approval to its proposal's hash and only lets approved approvals back an
execution; this adds expiry and that the proposal still hashes to what was approved.
"""

import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.actions.base import Facts, get_action
from app.core import audit, events
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Customer,
    ProposalSupersession,
    Transaction,
)
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext
from app.engine.eligibility import fair_use, order_facts
from app.engine.offer_state import open_offer
from app.engine.proposals import proposal_hash_is_intact

# A decision moves the case on only from these (an escalated or closed case stays put).
DECIDABLE_CASE_STATUSES = ("awaiting_approval", "executing")


class ApprovalError(Exception):
    """Base. `code` is safe to show; details stay in the audit log."""

    code = "approval_error"


class NotFound(ApprovalError):  # also used for out-of-scope: existence isn't confirmed
    code = "not_found"


class Forbidden(ApprovalError):
    code = "forbidden"


class AlreadyDecided(ApprovalError):
    code = "already_decided"


class WaitingForCustomer(ApprovalError):
    """An approver asked the customer to choose first (S8.10); nobody may approve until the
    customer answers or the time runs out."""

    code = "waiting_for_customer"


class NotEligible(ApprovalError):
    code = "not_eligible"

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Usability:
    ok: bool
    reason: str | None = None


def not_superseded():
    """SQL filter: proposals nobody switched away from (S7.10). Use it wherever "pending" or
    "the case's current proposal" is listed."""
    return ~exists().where(ProposalSupersession.old_proposal_id == ActionProposal.id)


def is_superseded(session: Session, proposal_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(ProposalSupersession.id).where(
                ProposalSupersession.old_proposal_id == proposal_id
            )
        )
        is not None
    )


def head_proposal_id(session: Session, proposal_id: uuid.UUID) -> uuid.UUID:
    """The proposal that replaced this one (following a chain of switches), or itself."""
    current = proposal_id
    for _ in range(20):  # a chain is short; the bound only guards against corrupt data
        nxt = session.scalar(
            select(ProposalSupersession.new_proposal_id).where(
                ProposalSupersession.old_proposal_id == current
            )
        )
        if nxt is None:
            return current
        current = nxt
    return current


def lock_case(session: Session, case_id: uuid.UUID) -> Case | None:
    """SELECT ... FOR UPDATE on the case: deciding and switching a proposal both take it first,
    so for one case they run one after the other and exactly one of them wins."""
    return session.execute(
        select(Case)
        .where(Case.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def check_usable(approval: Approval | None, proposal: ActionProposal, now: datetime) -> Usability:
    if approval is None:
        return Usability(False, "no_approval")
    db = object_session(proposal)
    if db is not None and is_superseded(db, proposal.id):  # belt and braces: decide refuses too
        return Usability(False, "superseded")
    if approval.proposal_id != proposal.id:
        return Usability(False, "approval_for_another_proposal")
    if approval.decision != "approved":
        return Usability(False, "rejected")
    if approval.payload_hash != proposal.payload_hash or not proposal_hash_is_intact(proposal):
        return Usability(False, "payload_changed")
    if now >= approval.expires_at:
        return Usability(False, "expired")
    return Usability(True)


def _order_id(session: Session, proposal: ActionProposal) -> uuid.UUID | None:
    case = session.get(Case, proposal.case_id)
    order_id = proposal.params.get("transaction_id") or (case and case.transaction_id)
    return uuid.UUID(str(order_id)) if order_id else None


def proposal_location(session: Session, proposal: ActionProposal) -> uuid.UUID | None:
    """The location a proposal concerns (its order's). None: no order, so hq_owner only
    (e.g. a loyalty credit on a case with no order) - intended, not a fallback gap."""
    order_id = _order_id(session, proposal)
    if order_id is None:
        return None
    order = session.get(Transaction, order_id)
    if order is None:
        raise LookupError("order not found")
    return order.location_id


def evaluate_proposal(session, ctx, proposal, now: datetime):
    """The action's own checks, plus the fair-use signal for compensation actions. Fair use
    only adds checks: it never makes a proposal ineligible (a person can still approve)."""
    action = get_action(proposal.action)()
    order_id = _order_id(session, proposal)
    if order_id is not None:
        _, facts = order_facts(session, order_id, exclude_proposal=proposal.id)
    else:
        facts = Facts(settings=effective_settings(session))
    inp = action.Input.model_validate_json(json.dumps(proposal.params))
    result = action.validate(ctx, inp, facts)
    if action.counts_as_grant:
        case = session.get(Case, proposal.case_id)
        usage = fair_use(session, case.customer_id, facts.settings, now, proposal.id)
        result = replace(result, checks={**result.checks, **usage.checks()})
    return action, inp, facts, result


def scoped_proposal(session: Session, ctx: TenantContext, proposal_id: uuid.UUID) -> ActionProposal:
    """The proposal if the caller is staff who may act on it; else NotFound. Scope first, and
    every failure looks like "not found": an out-of-scope proposal must be indistinguishable
    from one that doesn't exist (hard rule 8)."""
    proposal = session.get(ActionProposal, proposal_id)  # RLS: other tenants' don't exist
    if proposal is None or not ctx.is_staff:
        raise NotFound("proposal not found")
    try:
        location_id = proposal_location(session, proposal)
    except LookupError:
        raise NotFound("proposal not found") from None
    in_scope = ctx.role == "hq_owner" or (
        location_id is not None and ctx.can_see_location(location_id)
    )
    if not in_scope:
        raise NotFound("proposal not found")
    return proposal


def decide(
    session: Session,
    ctx: TenantContext,
    proposal_id: uuid.UUID,
    decision: str,
    now: datetime,
    note: str | None = None,
    *,
    self_approved: str | None = None,
) -> Approval:
    """A staff member approves or rejects a proposal in their scope.

    `self_approved` is for app/engine/switch.py only: it names the basis ("downgrade" or
    "owner_override") on which the proposal's own author may approve it. It skips only the
    four-eyes check; scope, limits and eligibility still apply, and the audit event says so."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    proposal = scoped_proposal(session, ctx, proposal_id)
    # Same lock as switching the remedy: if an approver switched this proposal first, it is
    # superseded and nobody may decide it any more (the new proposal has its own decision).
    lock_case(session, proposal.case_id)
    if is_superseded(session, proposal.id):
        raise AlreadyDecided("this proposal was superseded by another remedy")
    if decision == "approved" and open_offer(session, proposal.id, now) is not None:
        raise WaitingForCustomer("waiting for the customer to choose")
    if decision == "approved" and proposal.proposed_by == ctx.user_id and not self_approved:
        # Four eyes: whoever proposed a remedy cannot approve it (any path). Rejecting your own
        # proposal stays allowed: it is a withdrawal, not a payout.
        raise Forbidden("you proposed this remedy, so someone else must approve it")
    if not proposal_hash_is_intact(proposal):
        raise NotEligible(["proposal no longer matches its payload hash"])
    action, inp, facts, result = evaluate_proposal(session, ctx, proposal, now)
    if decision == "approved":
        if not result.ok:
            raise NotEligible(result.errors)  # eligibility is re-checked at decision time
        if result.checks.get("needs_hq") and ctx.role != "hq_owner":
            raise Forbidden("amount above the escalation limit needs an hq_owner")
    approval = Approval(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        proposal_id=proposal.id,
        payload_hash=proposal.payload_hash,  # binds to exactly what the approver saw
        decision=decision,
        mode="human",
        decided_by=ctx.user_id,
        decided_at=now,
        expires_at=now + timedelta(minutes=facts.settings["approval_expiry_minutes"]),
        note=note,
    )
    _insert(session, approval)
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event=f"approval.{decision}",
        entity_type="proposal",
        entity_id=proposal.id,
        payload={"checks": result.checks, "note": note}
        | ({"self_approved": True, "self_approval_basis": self_approved} if self_approved else {}),
    )
    case = session.get(Case, proposal.case_id)
    if case is not None and case.status in DECIDABLE_CASE_STATUSES:
        # Rejected: the case is closed (stage "declined"). Approved: execution comes next.
        case.status = "closed" if decision == "rejected" else "executing"
    events.emit(session, ctx.tenant_id, f"case.{decision}", proposal.case_id,
                {"proposal_id": str(proposal.id), "mode": "human"})  # fmt: skip
    return approval


def auto_decide(
    session: Session, tenant_id: uuid.UUID, proposal_id: uuid.UUID, now: datetime
) -> Approval | None:
    """Apply the tenant's auto-approve rule. Returns None when a human must decide.

    `tenant_id` must come from the auth or system context, never from input. The synthetic
    context built below is only for `validate` (which ignores identity); it must never reach
    scope- or role-sensitive code.
    """
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a UUID from the auth/system context")
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise NotFound("proposal not found")
    if not proposal_hash_is_intact(proposal):
        return None
    if proposal.proposed_by is not None:  # a person proposed it: another person decides (S7.5)
        return None
    if open_offer(session, proposal.id, now) is not None:  # asked the customer first (S8.10)
        return None
    action_cls = get_action(proposal.action)
    if not action_cls.auto_approvable:  # refunds: never (PROJECT.md section 2)
        return None
    # Serialise auto-approvals per customer, so two concurrent ones can't both read the same
    # fair-use count and both pass (the lock is held until this transaction commits).
    customer_id = session.scalar(select(Case.customer_id).where(Case.id == proposal.case_id))
    session.scalar(select(Customer.id).where(Customer.id == customer_id).with_for_update())
    system = TenantContext(
        tenant_id, uuid.UUID(int=0), uuid.UUID(int=0), "hq_owner", frozenset(), frozenset()
    )
    action, inp, facts, result = evaluate_proposal(session, system, proposal, now)
    if not result.ok or not action.can_auto_approve(inp, facts):
        return None
    if result.checks.get("fair_use_ok") is False:
        # Many recent grants: a person decides. Never an automatic denial either: the
        # proposal stays pending for a manager, who sees the count in the checks.
        audit.record(
            session,
            tenant_id,
            actor_type="system",
            actor_id=None,
            event="approval.auto_skipped",
            entity_type="proposal",
            entity_id=proposal.id,
            payload={"reason": "fair_use", "checks": result.checks},
        )
        return None
    approval = Approval(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        proposal_id=proposal.id,
        payload_hash=proposal.payload_hash,
        decision="approved",
        mode="auto",
        decided_by=None,
        decided_at=now,
        expires_at=now + timedelta(minutes=facts.settings["approval_expiry_minutes"]),
        note="auto-approved by tenant rule",
    )
    _insert(session, approval)
    audit.record(
        session,
        tenant_id,
        actor_type="system",
        actor_id=None,
        event="approval.auto",
        entity_type="proposal",
        entity_id=proposal.id,
        payload={"checks": result.checks},
    )
    return approval


def _insert(session: Session, approval: Approval) -> None:
    """One decision per proposal: a second one (another manager, a double submit) fails."""
    nested = session.begin_nested()
    try:
        session.add(approval)
        session.flush()
    except IntegrityError as exc:
        nested.rollback()
        existing = session.scalar(
            select(Approval.id).where(Approval.proposal_id == approval.proposal_id)
        )
        if existing is not None:
            raise AlreadyDecided("this proposal already has a decision") from exc
        raise
    nested.commit()
