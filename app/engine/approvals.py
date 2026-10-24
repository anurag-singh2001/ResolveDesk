"""Approval decisions and whether an approval may still be acted on (hard rule 6).

`decide` records a human decision; `auto_decide` applies a tenant's auto-approve rule (never
for refunds). `check_usable` is what the executor calls right before reserving money: the DB
already binds an approval to its proposal's hash and only lets approved approvals back an
execution; this adds expiry and that the proposal still hashes to what was approved.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.actions.base import Facts, get_action
from app.core import audit
from app.core.models import ActionProposal, Approval, Case
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext
from app.engine.eligibility import order_facts
from app.engine.proposals import proposal_hash_is_intact


class ApprovalError(Exception):
    """Base. `code` is safe to show; details stay in the audit log."""

    code = "approval_error"


class NotFound(ApprovalError):  # also used for out-of-scope: existence isn't confirmed
    code = "not_found"


class Forbidden(ApprovalError):
    code = "forbidden"


class AlreadyDecided(ApprovalError):
    code = "already_decided"


class NotEligible(ApprovalError):
    code = "not_eligible"

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Usability:
    ok: bool
    reason: str | None = None


def check_usable(approval: Approval | None, proposal: ActionProposal, now: datetime) -> Usability:
    if approval is None:
        return Usability(False, "no_approval")
    if approval.proposal_id != proposal.id:
        return Usability(False, "approval_for_another_proposal")
    if approval.decision != "approved":
        return Usability(False, "rejected")
    if approval.payload_hash != proposal.payload_hash or not proposal_hash_is_intact(proposal):
        return Usability(False, "payload_changed")
    if now >= approval.expires_at:
        return Usability(False, "expired")
    return Usability(True)


def proposal_facts(session: Session, proposal: ActionProposal) -> tuple[uuid.UUID | None, Facts]:
    """(location the proposal concerns, eligibility facts), read in the tenant's session."""
    case = session.get(Case, proposal.case_id)
    order_id = proposal.params.get("transaction_id") or (case and case.transaction_id)
    if order_id:
        order, facts = order_facts(session, uuid.UUID(str(order_id)), exclude_proposal=proposal.id)
        return order.location_id, facts
    return None, Facts(settings=effective_settings(session))


def _evaluate(session, ctx, proposal):
    action = get_action(proposal.action)()
    location_id, facts = proposal_facts(session, proposal)
    inp = action.Input.model_validate_json(json.dumps(proposal.params))
    return action, inp, location_id, facts, action.validate(ctx, inp, facts)


def decide(
    session: Session,
    ctx: TenantContext,
    proposal_id: uuid.UUID,
    decision: str,
    now: datetime,
    note: str | None = None,
) -> Approval:
    """A staff member approves or rejects a proposal in their scope."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    proposal = session.get(ActionProposal, proposal_id)  # RLS: other tenants' don't exist
    if proposal is None or not ctx.is_staff:
        raise NotFound("proposal not found")
    action, inp, location_id, facts, result = _evaluate(session, ctx, proposal)
    in_scope = ctx.role == "hq_owner" or (
        location_id is not None and ctx.can_see_location(location_id)
    )
    if not in_scope:
        raise NotFound("proposal not found")
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
        payload={"checks": result.checks, "note": note},
    )
    return approval


def auto_decide(
    session: Session, tenant_id: uuid.UUID, proposal_id: uuid.UUID, now: datetime
) -> Approval | None:
    """Apply the tenant's auto-approve rule. Returns None when a human must decide."""
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise NotFound("proposal not found")
    action_cls = get_action(proposal.action)
    if not action_cls.auto_approvable:  # refunds: never (PROJECT.md section 2)
        return None
    system = TenantContext(
        tenant_id, uuid.UUID(int=0), uuid.UUID(int=0), "hq_owner", frozenset(), frozenset()
    )
    action, inp, _, facts, result = _evaluate(session, system, proposal)
    if not result.ok or not action.can_auto_approve(inp, facts):
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
