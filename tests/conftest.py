from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app.api.deps import get_db_engine
from app.config import get_settings
from app.core.tenant_config import TenantConfig, load_tenant, tenant_dirs
from app.core.tenant_loader import load_pack_into_db, load_tenant_into_db
from app.core.verticals import load_pack
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


@pytest.fixture(scope="session")
def seeded(app_engine, owner_engine) -> dict[str, TenantConfig]:
    """All tenant folders loaded into the test database, keyed by folder name."""
    configs = {}
    for folder in tenant_dirs():
        cfg = load_tenant(folder)
        pack = load_pack(cfg.vertical_pack)
        load_pack_into_db(owner_engine, pack)
        load_tenant_into_db(app_engine, cfg, pack)
        configs[folder.name] = cfg
    return configs


@pytest.fixture
def api(app_engine, seeded) -> TestClient:
    """API client wired to the test database."""
    application = create_app()
    application.dependency_overrides[get_db_engine] = lambda: app_engine
    return TestClient(application)
