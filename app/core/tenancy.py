"""Who is acting, for which tenant, and what they may see. Built only from a verified token."""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, and_, false, func, select, true
from sqlalchemy.orm import Session

from app.core.models import (
    Customer,
    Membership,
    MembershipBrand,
    MembershipLocation,
    Transaction,
    User,
)

Role = Literal["customer", "location_manager", "franchisee_owner", "hq_owner"]
STAFF_ROLES: frozenset[str] = frozenset({"location_manager", "franchisee_owner", "hq_owner"})
LOCATION_SCOPED_ROLES: frozenset[str] = frozenset({"location_manager", "franchisee_owner"})

NAMESPACE = uuid.UUID("6f1c2a52-5f0e-4c7e-9a43-6a3e0b1d2c10")
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def tenant_id_for(slug: str) -> uuid.UUID:
    """Deterministic tenant id. Lets login find a tenant without reading across tenants."""
    return uuid.uuid5(NAMESPACE, f"org:{slug}")


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    role: Role
    brand_ids: frozenset[uuid.UUID]
    location_ids: frozenset[uuid.UUID]

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES

    def can_see_location(self, location_id: uuid.UUID) -> bool:
        if self.role == "hq_owner":
            return True
        # Scoped roles with no locations see nothing (fail closed), never the whole org.
        if self.role in LOCATION_SCOPED_ROLES:
            return location_id in self.location_ids
        return False

    def visible_orders(self) -> ColumnElement[bool]:
        """WHERE clause for the orders this caller may see (RLS already limits the tenant).

        Staff: location scope, narrowed by brand scope when the membership has brands.
        Customers: only orders of the customer record linked to their own user id; an order or
        customer id they send never widens this (hard rule 8).
        """
        if self.role == "customer":
            own = select(Customer.id).where(Customer.user_id == self.user_id)
            return Transaction.customer_id.in_(own)
        if self.role == "hq_owner":
            clause: ColumnElement[bool] = true()
        elif self.role in LOCATION_SCOPED_ROLES:
            clause = Transaction.location_id.in_(self.location_ids or [_NOTHING])
        else:
            return false()
        if self.brand_ids:
            clause = and_(clause, Transaction.brand_id.in_(self.brand_ids))
        return clause


# IN () is invalid SQL; a uuid no row has keeps "empty scope sees nothing" explicit.
_NOTHING = uuid.UUID(int=0)


def load_context(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> TenantContext | None:
    """Context from the DB (role/scope changes apply immediately). None if user is gone.

    `session` must already be scoped to tenant_id, so a user id from another tenant is invisible.
    """
    # One round trip (the DB is remote; this runs on every request): the user, their
    # memberships, and each membership's brand and location scope as arrays.
    brands = (
        select(func.array_agg(MembershipBrand.brand_id))
        .where(MembershipBrand.membership_id == Membership.id)
        .scalar_subquery()
    )
    locations = (
        select(func.array_agg(MembershipLocation.location_id))
        .where(MembershipLocation.membership_id == Membership.id)
        .scalar_subquery()
    )
    rows = session.execute(
        select(User.tenant_id, Membership.id, Membership.role, brands, locations)
        .outerjoin(Membership, Membership.user_id == User.id)
        .where(User.id == user_id)
    ).all()
    if not rows or rows[0][0] != tenant_id:
        return None
    if len(rows) != 1 or rows[0][1] is None:  # unique in the schema; fail closed
        return None
    _, membership_id, role, brand_ids, location_ids = rows[0]
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        membership_id=membership_id,
        role=role,
        brand_ids=frozenset(brand_ids or ()),
        location_ids=frozenset(location_ids or ()),
    )
