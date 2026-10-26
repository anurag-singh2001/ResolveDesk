"""Auth routes and helpers that need no database: demo accounts, CORS, password hashing."""

import pytest
from fastapi.testclient import TestClient

import app.api.routes_auth as routes_auth
from app.config import Settings, get_settings
from app.core.passwords import MAX_PASSWORD_BYTES, hash_password, verify_password
from app.core.tenant_config import load_tenant
from app.main import create_app


def test_demo_accounts_list_every_demo_user_outside_prod(tenant):
    cfg = load_tenant(tenant)
    resp = TestClient(create_app()).get("/auth/demo-accounts")
    assert resp.status_code == 200
    mine = {a["email"]: a for a in resp.json() if a["tenant"] == cfg.slug}
    for user in cfg.users:
        assert mine[user.email] == {
            "tenant": cfg.slug,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "password": cfg.demo_password_for(user),
        }


@pytest.mark.parametrize(
    "settings",
    [
        Settings(_env_file=None, app_env="prod", demo_auth=False, jwt_secret="s" * 48),
        Settings(_env_file=None, app_env="dev", demo_auth=False),
    ],
    ids=["prod", "demo-auth-off"],
)
def test_demo_accounts_are_404_in_prod_or_without_demo_auth(monkeypatch, settings):
    monkeypatch.setattr(routes_auth, "get_settings", lambda: settings)
    resp = TestClient(create_app()).get("/auth/demo-accounts")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "not found"}


def test_tenant_demo_passwords_are_long_enough_to_be_distinct(tenant):
    cfg = load_tenant(tenant)
    assert cfg.demo_password, "every tenant folder sets a demo_password"
    assert all(len(cfg.demo_password_for(u)) >= 8 for u in cfg.users)


def test_cors_allows_only_configured_origins():
    client = TestClient(create_app())
    allowed = get_settings().web_origin_list[0]
    preflight = {"Access-Control-Request-Method": "POST"}
    ok = client.options("/auth/login", headers={"Origin": allowed, **preflight})
    assert ok.headers.get("access-control-allow-origin") == allowed
    other = client.options("/auth/login", headers={"Origin": "https://evil.test", **preflight})
    assert "access-control-allow-origin" not in other.headers


def test_web_origins_default_and_list():
    assert Settings(_env_file=None, app_env="dev").web_origin_list == ["http://localhost:5173"]
    many = Settings(_env_file=None, app_env="dev", web_origins="https://a.test, https://b.test")
    assert many.web_origin_list == ["https://a.test", "https://b.test"]


def test_password_hash_roundtrip():
    stored = hash_password("correct horse", rounds=4)
    assert stored.startswith("$2") and "correct horse" not in stored
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)


@pytest.mark.parametrize("stored", [None, "", "not-a-bcrypt-hash"])
def test_no_or_bad_hash_never_verifies(stored):
    assert not verify_password("anything", stored)


def test_overlong_passwords_are_refused_not_truncated():
    long = "x" * MAX_PASSWORD_BYTES
    stored = hash_password(long, rounds=4)
    assert not verify_password(long + "y", stored)
    with pytest.raises(ValueError):
        hash_password(long + "y", rounds=4)
