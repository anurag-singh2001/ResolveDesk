"""Tenancy models. Every table carries tenant_id and is protected by RLS (see migrations)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("customer", "location_manager", "franchisee_owner", "hq_owner")


class Base(DeclarativeBase):
    pass


class TenantOwned:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )  # kept current by the set_updated_at trigger (migration 0002), also for raw SQL


class Organization(TenantOwned, Base):
    """The tenant itself: tenant_id == id, so the same RLS policy applies."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("tenant_id = id", name="ck_organizations_tenant_is_self"),
        UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    vertical_pack: Mapped[str] = mapped_column(String(64), nullable=False)


class Brand(TenantOwned, Base):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_brands_tenant_slug"),
        # Target for composite FKs: children reference (tenant_id, id) so they can't cross tenants.
        UniqueConstraint("tenant_id", "id", name="uq_brands_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Location(TenantOwned, Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_locations_tenant_slug"),
        UniqueConstraint("tenant_id", "id", name="uq_locations_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class LocationBrand(TenantOwned, Base):
    """Which brands a location serves (one kitchen can serve several brands)."""

    __tablename__ = "location_brands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "location_id", "brand_id", name="uq_location_brands"),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"], ondelete="CASCADE"
        ),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    brand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class User(TenantOwned, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)


class Membership(TenantOwned, Base):
    """A user's role. Scope rows live in membership_brands / membership_locations;
    no scope rows means the whole org (checked in code, 1d)."""

    __tablename__ = "memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "role IN ('customer', 'location_manager', 'franchisee_owner', 'hq_owner')",
            name="ck_memberships_role",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)


class MembershipBrand(TenantOwned, Base):
    __tablename__ = "membership_brands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "membership_id", "brand_id", name="uq_membership_brands"),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"], ondelete="CASCADE"
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    brand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class MembershipLocation(TenantOwned, Base):
    __tablename__ = "membership_locations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "membership_id", "location_id", name="uq_membership_locations"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            ondelete="CASCADE",
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


TENANT_MODELS = [
    Organization,
    Brand,
    Location,
    LocationBrand,
    User,
    Membership,
    MembershipBrand,
    MembershipLocation,
]
TENANT_TABLES = [m.__tablename__ for m in TENANT_MODELS]
