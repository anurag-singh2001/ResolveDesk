import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tenant_context
from app.config import Settings
from app.core.tenancy import TenantContext
from app.main import create_app
from mocks.registry import chaos_state, reset_mocks


def _ctx(role):
    return TenantContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), role, frozenset(), frozenset())


@pytest.fixture
def client_as():
    def make(role):
        app = create_app()
        app.dependency_overrides[get_tenant_context] = lambda: _ctx(role)
        return TestClient(app)

    yield make
    reset_mocks()


def test_hq_owner_sets_chaos(client_as):
    resp = client_as("hq_owner").post(
        "/admin/chaos", json={"service": "payment", "timeout_rate": 0.3}
    )
    assert resp.status_code == 200
    assert chaos_state()["payment"]["timeout_rate"] == 0.3


@pytest.mark.parametrize("role", ["customer", "location_manager", "franchisee_owner"])
def test_other_roles_cannot_set_chaos(client_as, role):
    resp = client_as(role).post("/admin/chaos", json={"service": "payment", "timeout_rate": 1})
    assert resp.status_code == 403
    assert chaos_state()["payment"]["timeout_rate"] == 0.0


@pytest.mark.parametrize("body", [{"service": "nope"}, {"service": "payment", "timeout_rate": 2}])
def test_invalid_chaos_rejected(client_as, body):
    assert client_as("hq_owner").post("/admin/chaos", json=body).status_code == 422


def test_admin_routes_do_not_exist_in_prod(monkeypatch):
    prod = Settings(_env_file=None, app_env="prod", demo_auth=False, jwt_secret="s" * 48)
    monkeypatch.setattr("app.main.get_settings", lambda: prod)
    app = create_app()
    app.dependency_overrides[get_tenant_context] = lambda: _ctx("hq_owner")
    assert TestClient(app).get("/admin/chaos").status_code == 404
