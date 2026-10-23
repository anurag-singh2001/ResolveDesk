"""Seeded tenants for isolation tests (app_engine lives in tests/conftest.py)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.exc import OperationalError

from app.core.db import tenant_session
from app.core.models import (
    TENANT_MODELS,
    ActionProposal,
    Approval,
    AuditEvent,
    Brand,
    Case,
    CatalogueItem,
    Consent,
    Customer,
    DomainEvent,
    Execution,
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
    RefundOperation,
    TenantSetting,
    Ticket,
    TicketMessage,
    Transaction,
    User,
    Verification,
    WorkflowRun,
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
    _seed_engine(s, t, customer_id, order_id, now)


def _seed_engine(s, t: SeededTenant, customer_id, order_id, now) -> None:
    """One row in every engine table (cases through the refund ledger, events, audit)."""
    tid = t.tenant_id
    case_id, run_id, proposal_id, approval_id, execution_id = (uuid.uuid4() for _ in range(5))
    digest = "0" * 64
    s.add(
        Case(
            id=case_id,
            tenant_id=tid,
            customer_id=customer_id,
            transaction_id=order_id,
            status="open",
            channel="app",
            opened_at=now,
        )
    )
    s.flush()
    s.add(WorkflowRun(id=run_id, tenant_id=tid, case_id=case_id, status="running"))
    s.flush()
    s.add(
        ActionProposal(
            id=proposal_id,
            tenant_id=tid,
            case_id=case_id,
            run_id=run_id,
            action="refund",
            params={"transaction_id": str(order_id), "amount_paise": 100, "reason": "test"},
            payload_hash=digest,
            amount_paise=100,
            amount_param="amount_paise",
            risk="high",
            reason="test",
        )
    )
    s.flush()
    s.add(
        Approval(
            id=approval_id,
            tenant_id=tid,
            proposal_id=proposal_id,
            payload_hash=digest,
            decision="approved",
            mode="human",
            decided_by=t.user_id,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    s.flush()
    s.add(
        Execution(
            id=execution_id,
            tenant_id=tid,
            proposal_id=proposal_id,
            approval_id=approval_id,
            idempotency_key=f"P-{proposal_id}:refund:1",
            status="submitted",
        )
    )
    s.add(
        RefundOperation(
            tenant_id=tid,
            transaction_id=order_id,
            proposal_id=proposal_id,
            idempotency_key=f"P-{proposal_id}:refund:1",
            amount_paise=100,
            status="reserved",
        )
    )
    s.flush()
    s.add(Verification(tenant_id=tid, execution_id=execution_id, status="unknown"))
    s.add(DomainEvent(tenant_id=tid, event="test.created", entity_id=case_id))
    s.add(AuditEvent(tenant_id=tid, actor_type="system", event="test", entity_type="case"))


def _cleanup(engine: Engine, t: SeededTenant, owner_engine: Engine) -> None:
    # The app role may not delete engine or audit rows (by design): clean up as the owner.
    # The owner bypasses RLS on Neon, so filter on tenant_id explicitly.
    with tenant_session(t.tenant_id, owner_engine) as s:
        for model in reversed(TENANT_MODELS):
            s.execute(delete(model).where(model.tenant_id == t.tenant_id))


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
def tenants(app_engine, owner_engine) -> tuple[SeededTenant, SeededTenant]:
    """Two freshly generated tenants (never a real tenant slug), shared per test module.

    Sharing is safe because the RLS tests only read, or attempt writes that must be rejected
    (a write that wrongly succeeded fails its own test). Seeding per test cost ~70 Neon round
    trips each and made the suite ~12 minutes."""
    a = _with_reconnect(_seed, app_engine)
    try:
        b = _with_reconnect(_seed, app_engine)
    except Exception:
        _cleanup(app_engine, a, owner_engine)
        raise
    yield a, b
    _cleanup(app_engine, a, owner_engine)
    _cleanup(app_engine, b, owner_engine)
