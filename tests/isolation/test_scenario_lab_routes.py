"""Scenario lab routes (S10.1) on the platform API. Needs the test database (the platform
audit call runs as the platform role). Runs over every tenant folder; never names a tenant.
The lab's disk folder is a temp copy, and no child process is ever started here."""

import shutil

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from app.api.deps import get_db_engine
from app.api.routes_platform import get_platform_engine
from app.config import get_settings
from app.core import scenario_lab as lab
from app.core.db import ENGINE_OPTIONS
from app.core.passwords import hash_password
from app.core.platform_auth import reset_failures
from app.main import create_app

pytestmark = pytest.mark.isolation

ROLE = "resolvedesk_platform"
EMAIL = "operator@example.test"
SECRET = "platform-only-secret-platform-only-secret-1"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAIL", EMAIL)
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=4))
    monkeypatch.setenv("PLATFORM_DATABASE_URL", "postgresql://unused.invalid/unused")
    monkeypatch.setenv("PLATFORM_JWT_SECRET", SECRET)
    monkeypatch.delenv("SCENARIO_LAB_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    reset_failures()
    lab.reset_for_tests()
    yield
    get_settings.cache_clear()
    reset_failures()
    lab.reset_for_tests()


@pytest.fixture(scope="module")
def platform_engine(app_engine):
    engine = create_engine(get_settings().test_migration_database_url, **ENGINE_OPTIONS)

    @event.listens_for(engine, "connect")
    def _switch(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute(f"SET ROLE {ROLE}")
        cur.close()
        dbapi_conn.commit()

    yield engine
    engine.dispose()


@pytest.fixture
def lab_client(tenant, app_engine, platform_engine, tmp_path, monkeypatch):
    root = tmp_path / "tenants"
    shutil.copytree(tenant, root / tenant.name)
    monkeypatch.setattr(lab, "TENANTS_DIR", root)
    monkeypatch.setattr(lab, "LAB_REPORTS", tmp_path / "reports" / "lab")
    application = create_app()
    application.dependency_overrides[get_db_engine] = lambda: app_engine
    application.dependency_overrides[get_platform_engine] = lambda: platform_engine
    client = TestClient(application)
    resp = client.post("/platform/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return client, headers, tenant.name, root / tenant.name


def test_lab_needs_the_platform_token(lab_client):
    client, _, slug, _ = lab_client
    assert client.get("/platform/lab/scenarios", params={"tenant": slug}).status_code == 401
    assert client.post("/platform/lab/runs", json={}).status_code == 401


def test_list_read_validate_and_save(lab_client):
    client, h, slug, folder = lab_client
    listing = client.get("/platform/lab/scenarios", params={"tenant": slug}, headers=h).json()
    assert listing["scenarios"] and listing["scratch_configured"] is False
    sid = listing["scenarios"][0]["id"]
    text = client.get(f"/platform/lab/scenarios/{slug}/{sid}", headers=h).json()["yaml"]

    ok = client.post(f"/platform/lab/validate/{slug}", json={"yaml": text}, headers=h).json()
    assert ok["ok"] is True and ok["id"] == sid
    bad = client.post(f"/platform/lab/validate/{slug}", json={"yaml": "a: [x"}, headers=h).json()
    assert bad["ok"] is False and "YAML" in bad["problems"][0]

    data = yaml.safe_load(text)
    data["id"] = "lab-copy-001"
    new = yaml.safe_dump(data)
    r = client.put(f"/platform/lab/scenarios/{slug}/lab-copy-001", json={"yaml": new}, headers=h)
    assert r.status_code == 200 and (folder / "scenarios" / "lab-copy-001.yaml").is_file()
    data["expect"]["category"] = "not_a_category"
    r = client.put(
        f"/platform/lab/scenarios/{slug}/lab-copy-001",
        json={"yaml": yaml.safe_dump(data)},
        headers=h,
    )
    assert r.status_code == 422 and "unknown category" in str(r.json())


def test_bad_names_and_other_tenants_are_not_found(lab_client):
    client, h, slug, _ = lab_client
    assert client.get("/platform/lab/scenarios/nobody/x", headers=h).status_code == 404
    assert client.get(f"/platform/lab/scenarios/{slug}/..%2Fx", headers=h).status_code == 404
    assert client.get(f"/platform/lab/scenarios/{slug}/no-such-one", headers=h).status_code == 404
    r = client.put(f"/platform/lab/scenarios/{slug}/..", json={"yaml": "id: x"}, headers=h)
    assert r.status_code in (404, 422)
    assert (
        client.get("/platform/lab/scenarios", params={"tenant": "nobody"}, headers=h).status_code
        == 404
    )


def test_a_run_without_a_scratch_database_is_refused_and_nothing_starts(lab_client, monkeypatch):
    client, h, slug, _ = lab_client
    sid = client.get("/platform/lab/scenarios", params={"tenant": slug}, headers=h).json()[
        "scenarios"
    ][0]["id"]
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: pytest.fail("must not start"))
    r = client.post(
        "/platform/lab/runs", json={"tenant": slug, "ids": [sid], "pipeline": "agents"}, headers=h
    )
    assert r.status_code == 503
    cur = client.get("/platform/lab/runs/current", headers=h).json()
    assert cur["status"] == "idle"


def test_a_scratch_database_equal_to_the_app_database_is_refused(lab_client, monkeypatch):
    client, h, slug, _ = lab_client
    app_db = get_settings().database_url.rsplit("/", 1)[-1].split("?")[0]
    monkeypatch.setenv("SCENARIO_LAB_DATABASE_URL", f"postgresql://u:p@elsewhere/{app_db}")
    get_settings.cache_clear()
    sid = client.get("/platform/lab/scenarios", params={"tenant": slug}, headers=h).json()[
        "scenarios"
    ][0]["id"]
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **k: pytest.fail("must not start"))
    r = client.post("/platform/lab/runs", json={"tenant": slug, "ids": [sid]}, headers=h)
    assert r.status_code == 503


def test_a_second_run_while_one_is_running_is_409(lab_client, monkeypatch):
    client, h, slug, _ = lab_client
    monkeypatch.setenv("SCENARIO_LAB_DATABASE_URL", "postgresql://u:p@h/lab_scratch_only")
    get_settings.cache_clear()
    sid = client.get("/platform/lab/scenarios", params={"tenant": slug}, headers=h).json()[
        "scenarios"
    ][0]["id"]
    import threading

    release = threading.Event()
    monkeypatch.setattr(
        lab.subprocess, "run", lambda *a, **k: release.wait(5) or type("P", (), {"returncode": 2})
    )
    body = {"tenant": slug, "ids": [sid], "pipeline": "agents"}
    first = client.post("/platform/lab/runs", json=body, headers=h)
    assert first.status_code == 202 and first.json()["status"] == "running"
    assert client.post("/platform/lab/runs", json=body, headers=h).status_code == 409
    release.set()
