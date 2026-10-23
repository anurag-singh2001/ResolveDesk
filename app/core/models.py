"""Tenancy models. Every table carries tenant_id and is protected by RLS (see migrations)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    """A user's role. Scope rows live in membership_brands / membership_locations.
    Only hq_owner sees the whole org; scoped roles with no rows see nothing (tenancy.py)."""

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
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
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


class VerticalPackRow(Base):
    """Platform-wide pack definition (not tenant-owned, so no tenant_id / RLS)."""

    __tablename__ = "vertical_packs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TenantSetting(TenantOwned, Base):
    """One override. Neither brand nor location = org level."""

    __tablename__ = "tenant_settings"
    __table_args__ = (
        CheckConstraint(
            "brand_id IS NULL OR location_id IS NULL", name="ck_tenant_settings_one_scope"
        ),
        UniqueConstraint(
            "tenant_id",
            "brand_id",
            "location_id",
            "key",
            name="uq_tenant_settings_scope_key",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"]),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
    )

    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)


class FeatureFlag(TenantOwned, Base):
    __tablename__ = "feature_flags"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_feature_flags_key"),)

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class CatalogueItem(TenantOwned, Base):
    __tablename__ = "catalogue_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_catalogue_items_sku"),
        ForeignKeyConstraint(["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"]),
        CheckConstraint("price_paise >= 0", name="ck_catalogue_items_price"),
    )

    brand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    price_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)


# Parents before children: cleanup code deletes in reverse order.
TENANT_MODELS = [
    Organization,
    Brand,
    Location,
    LocationBrand,
    User,
    Membership,
    MembershipBrand,
    MembershipLocation,
    TenantSetting,
    FeatureFlag,
    CatalogueItem,
]
TENANT_TABLES = [m.__tablename__ for m in TENANT_MODELS]
