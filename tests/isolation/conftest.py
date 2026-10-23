"""Seeded tenants for isolation tests (app_engine lives in tests/conftest.py)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.exc import OperationalError

from app.core.db import tenant_session
from app.core.models import (
    TENANT_MODELS,
    Brand,
    CatalogueItem,
    Consent,
    Customer,
    FeatureFlag,
    Fulfilment,
    LineItem,
    Location,
    LocationBrand,
    Membership,
    MembershipBrand,
    MembershipLocation,
    Organization,
    Payment,
    TenantSetting,
    Ticket,
    TicketMessage,
    Transaction,
    User,
)


@dataclass
class SeededTenant:
    tenant_id: uuid.UUID
    brand_id: uuid.UUID
    location_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID


def _seed(engine: Engine) -> SeededTenant:
    t = SeededTenant(*(uuid.uuid4() for _ in range(5)))
    tag = t.tenant_id.hex[:8]
    with tenant_session(t.tenant_id, engine) as s:
        s.add(
            Organization(
                id=t.tenant_id,
                tenant_id=t.tenant_id,
                slug=f"t-{tag}",
                name=tag,
                vertical_pack="test",
            )
        )
        s.flush()
        s.add(Brand(id=t.brand_id, tenant_id=t.tenant_id, slug="b", name="Brand"))
        s.add(Location(id=t.location_id, tenant_id=t.tenant_id, slug="l", name="Location"))
        s.add(
            User(
                id=t.user_id,
                tenant_id=t.tenant_id,
                email=f"{tag}@example.test",
                display_name="User",
            )
        )
        s.flush()
        s.add(LocationBrand(tenant_id=t.tenant_id, location_id=t.location_id, brand_id=t.brand_id))
        s.add(
            Membership(
                id=t.membership_id, tenant_id=t.tenant_id, user_id=t.user_id, role="hq_owner"
            )
        )
        s.flush()
        s.add(
            MembershipBrand(
                tenant_id=t.tenant_id, membership_id=t.membership_id, brand_id=t.brand_id
            )
        )
        s.add(
            MembershipLocation(
                tenant_id=t.tenant_id, membership_id=t.membership_id, location_id=t.location_id
            )
        )
        s.add(TenantSetting(tenant_id=t.tenant_id, key="voucher_max_paise", value=1000))
        s.add(FeatureFlag(tenant_id=t.tenant_id, key="growth", enabled=False))
        s.add(
            CatalogueItem(
                tenant_id=t.tenant_id,
                brand_id=t.brand_id,
                sku="SKU-1",
                name="Item",
                category="test",
                price_paise=100,
            )
        )
        s.flush()
        _seed_commerce(s, t)
    return t


def _seed_commerce(s, t: SeededTenant) -> None:
    """One row in every commerce table, so the generic RLS tests cover them too."""
    now = datetime.now(UTC)
    tid = t.tenant_id
    customer_id, order_id, ticket_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    s.add(Customer(id=customer_id, tenant_id=tid, external_ref="C1", name="Customer"))
    s.flush()
    s.add(
        Transaction(
            id=order_id,
            tenant_id=tid,
            customer_id=customer_id,
            brand_id=t.brand_id,
            location_id=t.location_id,
            source="test",
            external_ref="O1",
            placed_at=now,
            total_paise=100,
            status="completed",
        )
    )
    s.flush()
    s.add_all(
        [
            LineItem(
                tenant_id=tid,
                transaction_id=order_id,
                sku="SKU-1",
                name="Item",
                quantity=1,
                quantity_fulfilled=1,
                unit_price_paise=100,
                total_paise=100,
            ),
            Payment(
                tenant_id=tid,
                transaction_id=order_id,
                method="upi",
                amount_paise=100,
                status="captured",
                provider_reference="P1",
                captured_at=now,
            ),
            Fulfilment(
                tenant_id=tid,
                transaction_id=order_id,
                kind="pickup",
                promised_at=now,
                status="completed",
            ),
            Ticket(
                id=ticket_id,
                tenant_id=tid,
                customer_id=customer_id,
                transaction_id=order_id,
                category="test",
                status="open",
                channel="app",
                opened_at=now,
            ),
            Consent(
                tenant_id=tid,
                customer_id=customer_id,
                channel="whatsapp",
                purpose="marketing",
                granted=True,
            ),
        ]
    )
    s.flush()
    s.add(
        TicketMessage(tenant_id=tid, ticket_id=ticket_id, author="customer", body="hi", sent_at=now)
    )


def _cleanup(engine: Engine, t: SeededTenant) -> None:
    with tenant_session(t.tenant_id, engine) as s:
        for model in reversed(TENANT_MODELS):
            s.execute(delete(model))


def _with_reconnect(fn, engine, attempts: int = 3):
    """Neon's free tier sometimes drops a connection mid-statement. Retry setup only; the
    transaction rolled back, and a fresh tenant id is generated each attempt."""
    for attempt in range(attempts):
        try:
            return fn(engine)
        except OperationalError as exc:
            if not exc.connection_invalidated or attempt == attempts - 1:
                raise


@pytest.fixture(scope="module")
def tenants(app_engine) -> tuple[SeededTenant, SeededTenant]:
    """Two freshly generated tenants (never a real tenant slug), shared per test module.

    Sharing is safe because the RLS tests only read, or attempt writes that must be rejected
    (a write that wrongly succeeded fails its own test). Seeding per test cost ~70 Neon round
    trips each and made the suite ~12 minutes."""
    a = _with_reconnect(_seed, app_engine)
    try:
        b = _with_reconnect(_seed, app_engine)
    except Exception:
        _cleanup(app_engine, a)
        raise
    yield a, b
    _cleanup(app_engine, a)
    _cleanup(app_engine, b)
