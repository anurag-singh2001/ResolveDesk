"""GET/POST /admin/clock (dev panel): hq_owner only, bounded forward offset, absent in prod."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.api.deps as deps
from app.config import Settings
from app.main import create_app
from tests.helpers import login


@pytest.fixture(autouse=True)
def _clock_reset():
    deps.reset_clock()
    yield
    deps.reset_clock()


def _hq(api, seeded, tenant):
    cfg = seeded[tenant.name]
    return login(api, cfg.slug, next(u.email for u in cfg.users if u.role == "hq_owner"))


def test_get_returns_now_and_offset(api, seeded, tenant):
    resp = api.get("/admin/clock", headers=_hq(api, seeded, tenant))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["offset_seconds"] == 0
    assert abs(datetime.fromisoformat(body["now"]) - datetime.now(UTC)) < timedelta(seconds=30)


def test_advance_then_reset(api, seeded, tenant):
    h = _hq(api, seeded, tenant)
    resp = api.post("/admin/clock", headers=h, json={"advance_seconds": 3600})
    assert resp.status_code == 200 and resp.json()["offset_seconds"] == 3600
    resp = api.post("/admin/clock", headers=h, json={"advance_seconds": 86400})
    assert resp.json()["offset_seconds"] == 3600 + 86400
    assert deps.get_clock() > datetime.now(UTC) + timedelta(hours=24)
    resp = api.post("/admin/clock", headers=h, json={"reset": True})
    assert resp.json()["offset_seconds"] == 0
    assert deps.get_clock() < datetime.now(UTC) + timedelta(seconds=5)


def test_offset_is_bounded_and_never_goes_backwards(api, seeded, tenant):
    h = _hq(api, seeded, tenant)
    cap = int(deps.MAX_CLOCK_OFFSET.total_seconds())
    for _ in range(3):
        resp = api.post("/admin/clock", headers=h, json={"advance_seconds": cap})
        assert resp.status_code == 200
    assert resp.json()["offset_seconds"] == cap  # capped at 60 days
    for bad in ({"advance_seconds": -5}, {"advance_seconds": 0}, {"advance_seconds": cap + 1}, {}):
        assert api.post("/admin/clock", headers=h, json=bad).status_code == 422
    both = {"advance_seconds": 60, "reset": True}
    assert api.post("/admin/clock", headers=h, json=both).status_code == 422
    assert api.get("/admin/clock", headers=h).json()["offset_seconds"] == cap


def test_non_hq_roles_are_refused_and_nothing_moves(api, seeded, tenant):
    cfg = seeded[tenant.name]
    others = [u for u in cfg.users if u.role != "hq_owner"]
    assert others
    for user in others:
        h = login(api, cfg.slug, user.email)
        assert api.get("/admin/clock", headers=h).status_code == 403
        assert api.post("/admin/clock", headers=h, json={"advance_seconds": 60}).status_code == 403
    assert deps.clock_offset() == timedelta(0)


def test_clock_needs_a_token(api):
    assert api.get("/admin/clock").status_code == 401


def _prod(monkeypatch):
    prod = Settings(_env_file=None, app_env="prod", demo_auth=False, jwt_secret="s" * 48)
    monkeypatch.setattr("app.main.get_settings", lambda: prod)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: prod)


def test_routes_do_not_exist_in_prod(monkeypatch):
    _prod(monkeypatch)
    client = TestClient(create_app())
    assert client.get("/admin/clock").status_code == 404
    assert client.post("/admin/clock", json={"reset": True}).status_code == 404


def test_prod_get_clock_ignores_the_offset(monkeypatch):
    deps.advance_clock(timedelta(days=10))
    assert deps.get_clock() > datetime.now(UTC) + timedelta(days=9)  # dev/test applies it
    _prod(monkeypatch)
    assert deps.get_clock() < datetime.now(UTC) + timedelta(seconds=5)
