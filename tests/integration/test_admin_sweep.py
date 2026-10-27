"""POST /admin/sweep (dev panel): hq_owner only, own tenant only, absent in prod."""

import pytest
from fastapi.testclient import TestClient

import app.api.routes_admin as routes_admin
from app.config import Settings
from app.core.tenancy import tenant_id_for
from app.main import create_app
from tests.helpers import login

REPORT_KEYS = {
    "executed",
    "reconciled",
    "escalated_cases",
    "verified",
    "replies_resumed",
    "grievances_flagged",
    "pruned_threads",
    "events_published",
}


def test_hq_owner_sweeps_only_their_own_tenant(api, seeded, tenant, monkeypatch):
    cfg = seeded[tenant.name]
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    seen = []
    real = routes_admin.sweep_tenant

    def spy(engine, tenant_id, *a, **kw):
        seen.append(tenant_id)
        return real(engine, tenant_id, *a, **kw)

    monkeypatch.setattr(routes_admin, "sweep_tenant", spy)
    resp = api.post("/admin/sweep", headers=login(api, cfg.slug, hq.email))
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == REPORT_KEYS
    assert seen == [tenant_id_for(cfg.slug)]  # taken from the token, nothing else swept


def test_non_hq_roles_cannot_sweep(api, seeded, tenant, monkeypatch):
    cfg = seeded[tenant.name]
    monkeypatch.setattr(routes_admin, "sweep_tenant", lambda *a, **k: pytest.fail("swept"))
    others = [u for u in cfg.users if u.role != "hq_owner"]
    assert others
    for user in others:
        resp = api.post("/admin/sweep", headers=login(api, cfg.slug, user.email))
        assert resp.status_code == 403


def test_sweep_needs_a_token(api):
    assert api.post("/admin/sweep").status_code == 401


def test_sweep_route_does_not_exist_in_prod(monkeypatch):
    prod = Settings(_env_file=None, app_env="prod", demo_auth=False, jwt_secret="s" * 48)
    monkeypatch.setattr("app.main.get_settings", lambda: prod)
    assert TestClient(create_app()).post("/admin/sweep").status_code == 404
