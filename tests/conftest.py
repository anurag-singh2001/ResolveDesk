from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app.config import get_settings
from app.core.tenant_config import tenant_dirs
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(params=tenant_dirs(), ids=lambda p: p.name)
def tenant(request) -> Path:
    """Every folder under tenants/. Tests use this and never name a tenant."""
    return request.param


@pytest.fixture(scope="session")
def app_engine() -> Engine:
    """Test database as the RLS-bound app role, migrated to head."""
    s = get_settings()
    if not (s.test_database_url and s.test_migration_database_url):
        pytest.skip("TEST_DATABASE_URL / TEST_MIGRATION_DATABASE_URL not set")
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = s.test_migration_database_url
    command.upgrade(cfg, "head")
    engine = create_engine(s.test_database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def owner_engine(app_engine) -> Engine:
    """Owner role on the test database: only for platform-wide writes (vertical packs)."""
    engine = create_engine(get_settings().test_migration_database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()
