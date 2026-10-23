"""DB fixtures for isolation tests. Runs against the Neon `test` branch as the app role."""

import uuid
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete

from app.config import get_settings
from app.core.db import tenant_session
from app.core.models import (
    TENANT_MODELS,
    Brand,
    Location,
    LocationBrand,
    Membership,
    MembershipBrand,
    MembershipLocation,
    Organization,
    User,
)


@pytest.fixture(scope="session")
def app_engine() -> Engine:
    s = get_settings()
    if not (s.test_database_url and s.test_migration_database_url):
        pytest.skip("TEST_DATABASE_URL / TEST_MIGRATION_DATABASE_URL not set")
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = s.test_migration_database_url
    command.upgrade(cfg, "head")
    engine = create_engine(s.test_database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


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
