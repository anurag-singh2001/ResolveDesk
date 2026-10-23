"""Seeded tenants for isolation tests (app_engine lives in tests/conftest.py)."""

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, delete

from app.core.db import tenant_session
from app.core.models import (
    TENANT_MODELS,
    Brand,
    CatalogueItem,
    FeatureFlag,
    Location,
    LocationBrand,
    Membership,
    MembershipBrand,
    MembershipLocation,
    Organization,
    TenantSetting,
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
    return t


def _cleanup(engine: Engine, t: SeededTenant) -> None:
    with tenant_session(t.tenant_id, engine) as s:
        for model in reversed(TENANT_MODELS):
            s.execute(delete(model))


@pytest.fixture
def tenants(app_engine) -> tuple[SeededTenant, SeededTenant]:
    """Two freshly generated tenants (never a real tenant slug)."""
    a, b = _seed(app_engine), _seed(app_engine)
    yield a, b
    _cleanup(app_engine, a)
    _cleanup(app_engine, b)
