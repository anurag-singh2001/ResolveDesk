"""Models. Every tenant-owned table carries tenant_id and is protected by RLS (see migrations).
Money columns end in _paise and are bigint (hard rule 3)."""

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
    Text,
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


# --- Canonical commerce data (what connectors translate source systems into) -------------


def _fk(column: str, target: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    """Composite (tenant_id, x) -> target(tenant_id, id): a row can't point across tenants."""
    return ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], ondelete=ondelete
    )


class Customer(TenantOwned, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id"),
        UniqueConstraint("tenant_id", "external_ref", name="uq_customers_external_ref"),
        # Removing a login user unlinks the customer; only user_id is cleared (migration 0007).
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="SET NULL (user_id)",
            name="customers_tenant_id_user_id_fkey",
        ),
        _fk("home_location_id", "locations"),
    )

    external_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))  # not unique: real data has dupes
    email: Mapped[str | None] = mapped_column(String(320))
    # Set only for customers who can log in; ownership checks go through this link.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    home_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class Transaction(TenantOwned, Base):
    """An order (delivery, pickup or counter)."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_transactions_tenant_id"),
        UniqueConstraint("tenant_id", "source", "external_ref", name="uq_transactions_source_ref"),
        _fk("customer_id", "customers"),
        _fk("brand_id", "brands"),
        _fk("location_id", "locations"),
        CheckConstraint("total_paise >= 0", name="ck_transactions_total"),
        CheckConstraint(
            "status IN ('placed', 'completed', 'cancelled')", name="ck_transactions_status"
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    brand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class LineItem(TenantOwned, Base):
    __tablename__ = "line_items"
    __table_args__ = (
        _fk("transaction_id", "transactions", ondelete="CASCADE"),
        CheckConstraint("quantity > 0", name="ck_line_items_quantity"),
        CheckConstraint(
            "quantity_fulfilled BETWEEN 0 AND quantity", name="ck_line_items_fulfilled"
        ),
        CheckConstraint(
            "unit_price_paise >= 0 AND total_paise = unit_price_paise * quantity",
            name="ck_line_items_money",
        ),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Less than quantity = item missing from the order.
    quantity_fulfilled: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)


class Payment(TenantOwned, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payments_tenant_id"),
        _fk("transaction_id", "transactions", ondelete="CASCADE"),
        CheckConstraint("amount_paise > 0", name="ck_payments_amount"),
        CheckConstraint(
            "status IN ('captured', 'failed', 'refunded', 'partially_refunded')",
            name="ck_payments_status",
        ),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Fulfilment(TenantOwned, Base):
    __tablename__ = "fulfilments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "transaction_id", name="uq_fulfilments_transaction"),
        _fk("transaction_id", "transactions", ondelete="CASCADE"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled')", name="ck_fulfilments_status"
        ),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # delivery | pickup | counter
    promised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # e.g. {"wrong_item": true}; lateness is derived from promised_at vs completed_at.
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class Ticket(TenantOwned, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tickets_tenant_id"),
        _fk("customer_id", "customers"),
        _fk("transaction_id", "transactions"),
        CheckConstraint(
            "status IN ('open', 'resolved', 'escalated', 'closed')", name="ck_tickets_status"
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TicketMessage(TenantOwned, Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (
        _fk("ticket_id", "tickets", ondelete="CASCADE"),
        CheckConstraint(
            "author IN ('customer', 'system', 'staff')", name="ck_ticket_messages_author"
        ),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Consent(TenantOwned, Base):
    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "customer_id", "channel", "purpose", name="uq_consents_scope"
        ),
        _fk("customer_id", "customers", ondelete="CASCADE"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # whatsapp | sms | email
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)  # marketing | service
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)


# Loaded from tenant folders (the loader syncs these and only these).
CONFIG_MODELS = [
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
# Generated history / live operational data.
COMMERCE_MODELS = [
    Customer,
    Transaction,
    LineItem,
    Payment,
    Fulfilment,
    Ticket,
    TicketMessage,
    Consent,
]
# Parents before children: cleanup code deletes in reverse order.
TENANT_MODELS = CONFIG_MODELS + COMMERCE_MODELS
TENANT_TABLES = [m.__tablename__ for m in TENANT_MODELS]
