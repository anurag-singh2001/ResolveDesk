"""Case ownership (S7.2): who is responsible for a case that needs a person.

A case "needs a person" when it is escalated or awaiting a staff approval. The owner is chosen
from the tenant's own memberships (never a tenant-specific branch), deterministically:

1. needs HQ (the case's proposal is above refund_without_escalation_paise) or no outlet -> an
   hq_owner;
2. else the location_manager of the order's outlet;
3. else the franchisee_owner of that outlet;
4. else an hq_owner.

Several candidates: the lowest user id wins. Ownership is about responsibility only: who may
*decide* an approval is still approvals.decide's scope check, which this module never touches.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import (
    ActionProposal,
    Case,
    Membership,
    MembershipLocation,
    Transaction,
    User,
)
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext, load_context

NEEDS_PERSON_STATUSES = ("escalated", "awaiting_approval")


class NotAssignable(Exception):
    """The target user cannot own this case (not staff, or cannot see its outlet)."""


class NotAllowed(Exception):
    """The caller may see the case but may not change its owner."""


class NotNeedingPerson(Exception):
    """The case is not in a state that needs a person."""


def case_location(session: Session, case: Case) -> uuid.UUID | None:
    if case.transaction_id is None:
        return None
    return session.scalar(
        select(Transaction.location_id).where(Transaction.id == case.transaction_id)
    )


def needs_hq(session: Session, case: Case) -> bool:
    """The case's latest proposal is above the amount the outlet may handle on its own."""
    amount = session.scalar(
        select(ActionProposal.amount_paise)
        .where(ActionProposal.case_id == case.id)
        .order_by(ActionProposal.created_at.desc(), ActionProposal.id.desc())
        .limit(1)
    )
    if amount is None:
        return False
    limit = effective_settings(session).get("refund_without_escalation_paise")
    return limit is not None and amount > limit


def _lowest_user(session: Session, role: str, location_id: uuid.UUID | None) -> uuid.UUID | None:
    query = (
        select(Membership.user_id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.role == role, User.erased_at.is_(None))
        .order_by(Membership.user_id)
        .limit(1)
    )
    if location_id is not None:
        query = query.join(
            MembershipLocation, MembershipLocation.membership_id == Membership.id
        ).where(MembershipLocation.location_id == location_id)
    return session.scalar(query)


def pick_owner(session: Session, case: Case) -> uuid.UUID | None:
    location_id = case_location(session, case)
    if location_id is not None and not needs_hq(session, case):
        for role in ("location_manager", "franchisee_owner"):
            found = _lowest_user(session, role, location_id)
            if found is not None:
                return found
    return _lowest_user(session, "hq_owner", None)


def assign_owner(session: Session, tenant_id: uuid.UUID, case: Case, now: datetime) -> None:
    """Give a case that needs a person its owner. Idempotent: an owner already set (by the
    engine or by a person) is kept."""
    if case.owner_user_id is not None or case.status not in NEEDS_PERSON_STATUSES:
        return
    owner = pick_owner(session, case)
    if owner is None:
        return
    case.owner_user_id = owner
    case.owner_assigned_at = now
    audit.record(
        session,
        tenant_id,
        actor_type="system",
        actor_id=None,
        event="case.owner_assigned",
        entity_type="case",
        entity_id=case.id,
        payload={"owner_user_id": str(owner), "auto": True},
    )


def reassign(
    session: Session, ctx: TenantContext, case: Case, user_id: uuid.UUID, now: datetime
) -> None:
    """franchisee_owner / hq_owner hand a case to a staff user who can see its outlet.
    The caller has already established that they can see the case (else 404)."""
    if ctx.role not in ("franchisee_owner", "hq_owner"):
        raise NotAllowed("only a franchisee owner or HQ can change the owner")
    if case.status not in NEEDS_PERSON_STATUSES:
        raise NotNeedingPerson("the case does not need a person")
    target = load_context(session, ctx.tenant_id, user_id)
    if target is None or not target.is_staff:
        raise NotAssignable("the new owner must be a staff member")
    location_id = case_location(session, case)
    if location_id is None:
        if target.role != "hq_owner":
            raise NotAssignable("a case with no outlet can only be owned by HQ")
    elif not target.can_see_location(location_id):
        raise NotAssignable("the new owner cannot see this outlet")
    previous = case.owner_user_id
    case.owner_user_id = user_id
    case.owner_assigned_at = now
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.owner_changed",
        entity_type="case",
        entity_id=case.id,
        payload={
            "owner_user_id": str(user_id),
            "previous_owner_user_id": str(previous) if previous else None,
        },
    )
