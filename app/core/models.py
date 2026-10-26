"""Models. Every tenant-owned table carries tenant_id and is protected by RLS (see migrations).
Money columns end in _paise and are bigint (hard rule 3)."""

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("customer", "location_manager", "franchisee_owner", "hq_owner")
EMBEDDING_DIMS = 384  # BAAI/bge-small-en-v1.5


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
    # bcrypt hash; NULL = this user can't log in with a password (migration 0013).
    password_hash: Mapped[str | None] = mapped_column(Text)
    # The hash is of a demo password from the tenant folder: only accepted while demo
    # accounts are enabled (DEMO_AUTH on, not prod), even if the hash is still stored.
    password_is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class LoginFailure(TenantOwned, Base):
    """One failed login for (tenant, email), for the lockout window (migration 0013).

    The email is stored as a sha256 of its normalised form: attackers type arbitrary
    strings here, and the table only needs to count them. Insert/select/delete for the app.
    """

    __tablename__ = "login_failures"
    __table_args__ = (Index("ix_login_failures_key_time", "tenant_id", "email_hash", "failed_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    # The customer's own choice (en / hi-Latn / hi); never inferred. Migration 0018.
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
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
        # Order lookups: a customer's orders, and a location's orders by time (migration 0006).
        Index("ix_transactions_tenant_customer", "tenant_id", "customer_id"),
        Index("ix_transactions_tenant_location_placed", "tenant_id", "location_id", "placed_at"),
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
        # A live case's conversation (migration 0011). Clearing a case only unlinks it.
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            ["cases.tenant_id", "cases.id"],
            ondelete="SET NULL (case_id)",
            name="fk_tickets_case",
        ),
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
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)


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


# --- Engine (PROJECT.md section 7 "Engine", "Money", "Trust") ---------------------------


class Case(TenantOwned, Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cases_tenant_id"),
        _fk("customer_id", "customers"),
        _fk("transaction_id", "transactions"),
        CheckConstraint(
            "status IN ('open', 'investigating', 'awaiting_info', 'awaiting_approval', "
            "'executing', 'resolved', 'escalated', 'closed')",
            name="ck_cases_status",
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    category: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # DB/admin only (no API path): the retention job skips held cases (migration 0017).
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class WorkflowRun(TenantOwned, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_workflow_runs_tenant_id"),
        UniqueConstraint("tenant_id", "id", "case_id", name="uq_workflow_runs_tenant_id_case"),
        _fk("case_id", "cases", ondelete="CASCADE"),
        CheckConstraint(
            "status IN ('running', 'paused', 'completed', 'escalated', 'failed')",
            name="ck_workflow_runs_status",
        ),
        CheckConstraint("step_count >= 0 AND llm_calls >= 0", name="ck_workflow_runs_counters"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)


class ActionProposal(TenantOwned, Base):
    """Immutable (UPDATE blocked by trigger). payload_hash = sha256 of canonical JSON of
    {action, case_id, params}; approvals reference (id, payload_hash) together."""

    __tablename__ = "action_proposals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_action_proposals_tenant_id"),
        UniqueConstraint("tenant_id", "id", "payload_hash", name="uq_action_proposals_id_hash"),
        _fk("case_id", "cases", ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id", "case_id"],
            ["workflow_runs.tenant_id", "workflow_runs.id", "workflow_runs.case_id"],
            name="fk_action_proposals_run_case",
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_action_proposals_hash"),
        CheckConstraint(
            "(amount_param IS NULL AND amount_paise IS NULL) OR "
            "(amount_param IS NOT NULL AND (params ->> amount_param)::bigint = amount_paise)",
            name="ck_action_proposals_amount_matches_params",
        ),
        CheckConstraint(
            "amount_paise IS NULL OR amount_paise > 0", name="ck_action_proposals_amount"
        ),
        CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_action_proposals_risk"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    # Which param amount_paise was copied from; a DB check keeps the two equal.
    amount_param: Mapped[str | None] = mapped_column(String(64))
    risk: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    validation: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class Approval(TenantOwned, Base):
    """One decision per proposal, bound to the hash the approver saw (hard rule 6)."""

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_approvals_tenant_id"),
        UniqueConstraint("tenant_id", "proposal_id", name="uq_approvals_one_per_proposal"),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id", "payload_hash"],
            [
                "action_proposals.tenant_id",
                "action_proposals.id",
                "action_proposals.payload_hash",
            ],
            ondelete="CASCADE",
        ),
        _fk("decided_by", "users"),
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_approvals_decision"),
        CheckConstraint("mode IN ('human', 'auto')", name="ck_approvals_mode"),
        CheckConstraint(
            "(mode = 'human') = (decided_by IS NOT NULL)", name="ck_approvals_human_has_user"
        ),
        CheckConstraint("expires_at > decided_at", name="ck_approvals_expiry"),
        CheckConstraint(
            "expires_at <= decided_at + interval '7 days'", name="ck_approvals_expiry_cap"
        ),
        # Target for executions: (approval, its proposal, decision) must match together.
        UniqueConstraint("tenant_id", "id", "proposal_id", "decision", name="uq_approvals_binding"),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


EXECUTION_STATUSES = "('submitted', 'processing', 'succeeded', 'failed', 'unknown')"


class Execution(TenantOwned, Base):
    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_executions_tenant_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_executions_key"),
        UniqueConstraint("tenant_id", "proposal_id", name="uq_executions_one_per_proposal"),
        _fk("proposal_id", "action_proposals", ondelete="CASCADE"),
        # Only an APPROVED approval OF THIS proposal can back an execution.
        ForeignKeyConstraint(
            ["tenant_id", "approval_id", "proposal_id", "approval_decision"],
            ["approvals.tenant_id", "approvals.id", "approvals.proposal_id", "approvals.decision"],
            ondelete="CASCADE",
            name="fk_executions_approved_approval_of_proposal",
        ),
        CheckConstraint("approval_decision = 'approved'", name="ck_executions_only_approved"),
        CheckConstraint(f"status IN {EXECUTION_STATUSES}", name="ck_executions_status"),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_decision: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="approved"
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    # True only where we know no request reached the provider (refused, released).
    never_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Verification(TenantOwned, Base):
    __tablename__ = "verifications"
    __table_args__ = (
        _fk("execution_id", "executions", ondelete="CASCADE"),
        CheckConstraint(
            "status IN ('verified', 'mismatch', 'unknown')", name="ck_verifications_status"
        ),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class RefundOperation(TenantOwned, Base):
    """The money ledger for refunds (PROJECT.md section 10). Reserved before the provider call,
    so the refundable balance check can count in-flight refunds."""

    __tablename__ = "refund_operations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_refund_operations_key"),
        # One reservation per proposal; a trigger checks amount + order match it (0009).
        UniqueConstraint("tenant_id", "proposal_id", name="uq_refund_operations_one_per_proposal"),
        _fk("transaction_id", "transactions"),
        _fk("proposal_id", "action_proposals"),
        CheckConstraint("amount_paise > 0", name="ck_refund_operations_amount"),
        CheckConstraint(
            "status IN ('reserved', 'submitted', 'succeeded', 'failed', 'unknown', "
            "'pending_reconciliation', 'released')",
            name="ck_refund_operations_status",
        ),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(Base):
    """Append-only trail. The app role may only INSERT/SELECT (no updated_at by design)."""

    __tablename__ = "audit_events"
    append_only = True

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user | system | agent
    actor_id: Mapped[str | None] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")  # redacted


class DomainEvent(TenantOwned, Base):
    """Outbox for the in-process event bus (subscribers: notifications, metrics)."""

    __tablename__ = "domain_events"

    event: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. refund.succeeded
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Policies (PROJECT.md section 11) ----------------------------------------------------


class PolicyDocument(TenantOwned, Base):
    """One version of one policy. Scope: org (no brand/location), a brand, or a location."""

    __tablename__ = "policy_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_policy_documents_tenant_id"),
        UniqueConstraint("tenant_id", "doc_key", name="uq_policy_documents_key"),
        ForeignKeyConstraint(["tenant_id", "brand_id"], ["brands.tenant_id", "brands.id"]),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
        CheckConstraint("brand_id IS NULL OR location_id IS NULL", name="ck_policy_one_scope"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="ck_policy_window"
        ),
    )

    doc_key: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. late_delivery_v3
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_uri: Mapped[str] = mapped_column(String(300), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class PolicyChunk(TenantOwned, Base):
    """One section of a policy with its embedding. Content is untrusted (hard rule 9)."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "section_ref", name="uq_policy_chunks_ref"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["policy_documents.tenant_id", "policy_documents.id"],
            ondelete="CASCADE",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    section_ref: Mapped[str] = mapped_column(String(120), nullable=False)  # late_delivery_v3#2.1
    heading: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMS), nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")


# --- Growth (PROJECT.md section 17) ----------------------------------------------------


class Signal(TenantOwned, Base):
    """A flagged metric drop at one location. Rates are basis points (integers, no floats)."""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_signals_tenant_id"),
        # One signal per location, metric and recent window: re-running the job is a no-op.
        UniqueConstraint(
            "tenant_id", "location_id", "metric", "recent_end", name="uq_signals_window"
        ),
        _fk("location_id", "locations"),
        CheckConstraint("status IN ('open', 'actioned', 'dismissed')", name="ck_signals_status"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    baseline_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recent_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recent_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_n: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_n: Mapped[int] = mapped_column(Integer, nullable=False)
    drop_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    diagnosis: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    diagnosis_source: Mapped[str] = mapped_column(String(16), nullable=False)  # template | llm


CAMPAIGN_STATUSES = (
    "('pending_approval', 'approved', 'executing', 'sent', 'rejected', 'expired', 'measured')"
)


class Campaign(TenantOwned, Base):
    """A win-back proposal bound to a payload hash. The hash covers the signal, location, params
    and the exact audience (treatment + holdout ids), so an approval can't be replayed against
    a different audience or offer. Only `status` and `sent_at` change after creation."""

    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_campaigns_tenant_id"),
        UniqueConstraint("tenant_id", "id", "payload_hash", name="uq_campaigns_id_hash"),
        UniqueConstraint("tenant_id", "signal_id", name="uq_campaigns_one_per_signal"),
        _fk("signal_id", "signals"),
        _fk("location_id", "locations"),
        _fk("created_by", "users"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_campaigns_hash"),
        CheckConstraint(f"status IN {CAMPAIGN_STATUSES}", name="ck_campaigns_status"),
        CheckConstraint("budget_paise >= 0", name="ck_campaigns_budget"),
    )

    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    audience_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    budget_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignMember(TenantOwned, Base):
    """One audience member, assigned to treatment or holdout when the proposal is made."""

    __tablename__ = "campaign_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_id", "customer_id", name="uq_campaign_member"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_campaign_member_key"),
        _fk("campaign_id", "campaigns", ondelete="CASCADE"),
        _fk("customer_id", "customers"),
        CheckConstraint("arm IN ('treatment', 'holdout')", name="ck_campaign_members_arm"),
        CheckConstraint(
            "send_status IN ('pending', 'submitted', 'processing', 'succeeded', 'failed', "
            "'unknown')",
            name="ck_campaign_members_send_status",
        ),
        # Holdout members are never contacted.
        CheckConstraint(
            "arm = 'treatment' OR send_status = 'pending'", name="ck_campaign_members_holdout"
        ),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    arm: Mapped[str] = mapped_column(String(10), nullable=False)
    send_status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(120))


class CampaignApproval(TenantOwned, Base):
    """One decision per (campaign, user), bound to the hash that user saw. Never edited."""

    __tablename__ = "campaign_approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_id", "decided_by", name="uq_campaign_approver"),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id", "payload_hash"],
            ["campaigns.tenant_id", "campaigns.id", "campaigns.payload_hash"],
            ondelete="CASCADE",
        ),
        _fk("decided_by", "users"),
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_campaign_approvals_dec"),
        CheckConstraint("expires_at > decided_at", name="ck_campaign_approvals_expiry"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlaybookEntry(TenantOwned, Base):
    """What a measured campaign taught us: one row per campaign."""

    __tablename__ = "playbook_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_id", name="uq_playbook_one_per_campaign"),
        _fk("campaign_id", "campaigns", ondelete="CASCADE"),
        _fk("location_id", "locations"),
        CheckConstraint(
            "verdict IN ('worked', 'did_not_work', 'inconclusive')", name="ck_playbook_verdict"
        ),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    treatment_n: Mapped[int] = mapped_column(Integer, nullable=False)
    treatment_repeat: Mapped[int] = mapped_column(Integer, nullable=False)
    holdout_n: Mapped[int] = mapped_column(Integer, nullable=False)
    holdout_repeat: Mapped[int] = mapped_column(Integer, nullable=False)
    uplift_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_note: Mapped[str] = mapped_column(Text, nullable=False)
    lesson: Mapped[str] = mapped_column(Text, nullable=False)


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
# Cases, proposals, approvals, executions and the refund ledger: they reference commerce rows,
# so reseeding history (dev only) clears them first.
ENGINE_MODELS = [
    Case,
    WorkflowRun,
    ActionProposal,
    Approval,
    Execution,
    Verification,
    RefundOperation,
    DomainEvent,
]
# Auth bookkeeping (lockout counters); not config, not history.
AUTH_MODELS = [LoginFailure]
# Append-only; never deleted by reseed or the loader (no app-role DELETE privilege).
APPEND_ONLY_MODELS = [AuditEvent]
# Policy documents + chunks (written by app/rag/ingest.py, not the tenant loader).
POLICY_MODELS = [PolicyDocument, PolicyChunk]
# Growth tables reference commerce rows (customers, locations): reseeding clears them first.
GROWTH_MODELS = [Signal, Campaign, CampaignMember, CampaignApproval, PlaybookEntry]
# Parents before children: cleanup code deletes in reverse order.
TENANT_MODELS = (
    CONFIG_MODELS
    + AUTH_MODELS
    + POLICY_MODELS
    + COMMERCE_MODELS
    + ENGINE_MODELS
    + GROWTH_MODELS
    + APPEND_ONLY_MODELS
)
TENANT_TABLES = [m.__tablename__ for m in TENANT_MODELS]
