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

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import (
    ActionProposal,
    Case,
    Membership,
    MembershipBrand,
    MembershipLocation,
    Transaction,
    User,
)
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext, load_context
from app.engine.approvals import not_superseded

NEEDS_PERSON_STATUSES = ("escalated", "awaiting_approval")
BACKFILL_BATCH = 200


# What the queue shows as the reason. Stored reasons (audit payloads, proposal reasons) can quote
# a model or the customer, so the API returns only one of these fixed codes and labels.
REASON_LABELS = {
    "needs_approval": "Waiting for a staff decision",
    "safety_review": "Possible safety report: a manager must review it first",
    "customer_chose": "The customer chose an option: review it",
    "no_customer_answer": "The customer did not answer: decide on the original request",
    "ai_unavailable": "The AI could not finish this case",
    "payment_check": "A payment or refund needs checking",
    "no_automatic_remedy": "No automatic remedy applies",
    "privacy": "Privacy request",
    "other": "Escalated to a person",
}


def reason_code(
    status: str,
    category: str | None,
    event: str | None,
    raw: str,
    payment_started: bool,
    ai_failure: bool = False,
) -> str:
    """Map a case to a fixed reason code. `raw` is only compared against the prefixes the code
    itself writes; it is never returned. `ai_failure` comes from ai_rerun.is_ai_failure, which
    also recognises escalations written before the explicit code existed (reason text)."""
    if status == "awaiting_approval":
        return "needs_approval"
    if category == "privacy_request":
        return "privacy"
    if raw.startswith(("execution refused", "refund released")):
        return "payment_check"
    if ai_failure or raw.startswith(("customer replied but", "agent run did not finish")):
        return "ai_unavailable"
    if event == "case.escalate":  # the deterministic path's own "no remedy" decision
        return "no_automatic_remedy"
    if payment_started:  # escalated after a refund/voucher was approved: verification failed
        return "payment_check"
    return "other"


class NotAssignable(Exception):
    """The target user cannot own this case (not staff, or cannot see its outlet)."""


class NotAllowed(Exception):
    """The caller may see the case but may not change its owner."""


class NotNeedingPerson(Exception):
    """The case is not in a state that needs a person."""


def case_brand(session: Session, case: Case) -> uuid.UUID | None:
    if case.transaction_id is None:
        return None
    return session.scalar(select(Transaction.brand_id).where(Transaction.id == case.transaction_id))


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
        .where(ActionProposal.case_id == case.id, not_superseded())
        .order_by(ActionProposal.created_at.desc(), ActionProposal.id.desc())
        .limit(1)
    )
    if amount is None:
        return False
    limit = effective_settings(session).get("refund_without_escalation_paise")
    return limit is not None and amount > limit


def _lowest_user(
    session: Session, role: str, location_id: uuid.UUID | None, brand_id: uuid.UUID | None
) -> uuid.UUID | None:
    query = (
        select(Membership.user_id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.role == role, User.erased_at.is_(None))
        .order_by(Membership.user_id)
        .limit(1)
    )
    if brand_id is not None:
        # A membership with brand rows is limited to those brands (tenancy.visible_orders).
        has_brands = exists().where(MembershipBrand.membership_id == Membership.id)
        has_this = exists().where(
            MembershipBrand.membership_id == Membership.id, MembershipBrand.brand_id == brand_id
        )
        query = query.where(or_(~has_brands, has_this))
    if location_id is not None:
        query = query.join(
            MembershipLocation, MembershipLocation.membership_id == Membership.id
        ).where(MembershipLocation.location_id == location_id)
    return session.scalar(query)


def pick_owner(session: Session, case: Case) -> uuid.UUID | None:
    location_id = case_location(session, case)
    brand_id = case_brand(session, case)
    # A case with no order has no outlet: HQ-only by design (same rule as visible_case).
    if location_id is not None and not needs_hq(session, case):
        for role in ("location_manager", "franchisee_owner"):
            found = _lowest_user(session, role, location_id, brand_id)
            if found is not None:
                return found
    return _lowest_user(session, "hq_owner", None, brand_id)


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


def backfill_owners(session: Session, tenant_id: uuid.UUID, now: datetime) -> list[uuid.UUID]:
    """Give an owner to cases that already needed a person before ownership existed (S7.2).
    Only cases with no owner are touched, and only their owner fields change (assign_owner
    audits each one), so a second run finds nothing to do. Returns the cases that got one."""
    cases = session.scalars(
        select(Case)
        .where(Case.owner_user_id.is_(None), Case.status.in_(NEEDS_PERSON_STATUSES))
        .order_by(Case.opened_at, Case.id)
        .limit(BACKFILL_BATCH)  # a big backlog drains over several passes
        .with_for_update(skip_locked=True)  # a concurrent pass or a person's hand-over wins
    ).all()
    done = []
    for case in cases:
        assign_owner(session, tenant_id, case, now)
        if case.owner_user_id is not None:
            done.append(case.id)
    return done


def reassign(
    session: Session, ctx: TenantContext, case: Case, user_id: uuid.UUID, now: datetime
) -> None:
    """franchisee_owner / hq_owner hand a case to a staff user who can see its outlet.
    The caller has already established that they can see the case (else 404)."""
    if ctx.role not in ("franchisee_owner", "hq_owner"):
        raise NotAllowed("only a franchisee owner or HQ can change the owner")
    # Lock the row so two hand-overs serialise and the audited previous owner is the real one.
    case = session.execute(
        select(Case)
        .where(Case.id == case.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
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
    brand_id = case_brand(session, case)
    if brand_id is not None and target.brand_ids and brand_id not in target.brand_ids:
        raise NotAssignable("the new owner is not scoped to this order's brand")
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
