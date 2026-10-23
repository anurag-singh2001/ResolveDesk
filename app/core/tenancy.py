"""Who is acting, for which tenant, and what they may see. Built only from a verified token."""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Membership, MembershipBrand, MembershipLocation, User

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


def load_context(
    session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> TenantContext | None:
    """Context from the DB (role/scope changes apply immediately). None if user is gone.

    `session` must already be scoped to tenant_id, so a user id from another tenant is invisible.
    """
    user = session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        return None
    membership = session.scalars(select(Membership).where(Membership.user_id == user_id)).first()
    if membership is None:
        return None
    brand_ids = session.scalars(
        select(MembershipBrand.brand_id).where(MembershipBrand.membership_id == membership.id)
    )
    location_ids = session.scalars(
        select(MembershipLocation.location_id).where(
            MembershipLocation.membership_id == membership.id
        )
    )
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        membership_id=membership.id,
        role=membership.role,
        brand_ids=frozenset(brand_ids),
        location_ids=frozenset(location_ids),
    )
