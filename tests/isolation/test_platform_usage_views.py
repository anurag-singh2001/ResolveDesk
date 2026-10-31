"""Platform portal read path (S9.5): aggregate-only AI usage and job run views.

Same fixtures as the S9.1 tests (imported so the platform role is exercised the same way).
Tests never name a tenant.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.config import get_settings
from app.core.db import tenant_session
from app.main import create_app
from tests.helpers import login
from tests.isolation.test_platform_admin import (  # noqa: F401  (fixtures)
    FORBIDDEN_FRAGMENTS,
    ROLE,
    _clean_settings,
    _platform_headers,
    _slugs,
    papi,
    platform_engine,
    platform_env,
)

pytestmark = pytest.mark.isolation

VIEWS = ["platform_llm_usage_v", "platform_job_runs_v"]
ROUTES = ["ai-usage", "jobs"]
# "tokens_in" and "tokens_out" are counts, not credentials: the one allowed exception.
COUNT_COLUMNS = {"tokens_in", "tokens_out"}


@pytest.mark.parametrize("path", ROUTES)
def test_tenant_token_is_403_and_no_token_is_401(papi, seeded, tenant, path):  # noqa: F811
    cfg = seeded[tenant.name]
    assert papi.get(f"/platform/{path}").status_code == 401
    for user in cfg.users:
        headers = login(papi, cfg.slug, user.email)
        assert papi.get(f"/platform/{path}", headers=headers).status_code == 403


@pytest.mark.parametrize("path", ROUTES)
def test_unconfigured_is_404(path, monkeypatch):
    for name in ("PLATFORM_ADMIN_EMAIL", "PLATFORM_ADMIN_PASSWORD_HASH", "PLATFORM_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.get(f"/platform/{path}", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "platform admin not enabled"
    get_settings.cache_clear()


def test_both_tenants_appear_in_usage_and_jobs(papi, app_engine, tenants):  # noqa: F811
    a, b = tenants
    slugs = {_slugs(app_engine, a), _slugs(app_engine, b)}
    headers = _platform_headers(papi)
    usage = papi.get("/platform/ai-usage", headers=headers)
    jobs = papi.get("/platform/jobs", headers=headers)
    assert usage.status_code == 200 and jobs.status_code == 200
    assert slugs <= {r["tenant_slug"] for r in usage.json()}
    assert slugs <= {r["tenant_slug"] for r in jobs.json()}
    assert all(0 <= r["finished_count"] <= r["run_count"] for r in jobs.json())
    for row in usage.json():
        assert row["call_count"] >= 0 and isinstance(row["cost_micro_paise"], int)


def test_totals_match_the_tenant_own_rows(papi, app_engine, tenants):  # noqa: F811
    a, _ = tenants
    slug = _slugs(app_engine, a)
    with tenant_session(a.tenant_id, app_engine) as s:
        own = s.execute(text("SELECT coalesce(sum(calls), 0) FROM llm_usage")).scalar()
        runs = s.execute(text("SELECT count(*) FROM job_runs")).scalar()
    headers = _platform_headers(papi)
    usage = papi.get("/platform/ai-usage", headers=headers).json()
    jobs = papi.get("/platform/jobs", headers=headers).json()
    assert sum(r["call_count"] for r in usage if r["tenant_slug"] == slug) == own
    assert sum(r["run_count"] for r in jobs if r["tenant_slug"] == slug) == runs


def test_reads_are_audited(papi, owner_engine):  # noqa: F811
    headers = _platform_headers(papi)
    for path in ROUTES:
        with owner_engine.connect() as c:
            before = c.execute(text("SELECT count(*) FROM platform_audit_events")).scalar()
        assert papi.get(f"/platform/{path}", headers=headers).status_code == 200
        with owner_engine.connect() as c:
            after = c.execute(text("SELECT count(*) FROM platform_audit_events")).scalar()
            route = c.execute(
                text("SELECT route FROM platform_audit_events ORDER BY occurred_at DESC LIMIT 1")
            ).scalar()
        assert after == before + 1
        assert route == f"GET /platform/{path}"


@pytest.mark.parametrize("table", ["llm_usage", "job_runs"])
def test_platform_role_cannot_select_the_raw_tables(platform_engine, table):  # noqa: F811
    with platform_engine.connect() as c, pytest.raises(ProgrammingError, match="permission denied"):
        c.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


def test_views_have_no_id_or_text_columns(platform_engine):  # noqa: F811
    with platform_engine.connect() as c:
        cols = c.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_name = ANY(:v)"
            ),
            {"v": VIEWS},
        ).all()
    assert {t for t, _ in cols} == set(VIEWS)
    bad = [
        (t, col)
        for t, col in cols
        if col not in COUNT_COLUMNS and any(f in col for f in FORBIDDEN_FRAGMENTS)
    ]
    assert bad == []
    assert [(t, col) for t, col in cols if col == "id" or col.endswith("_id")] == []
    assert not any("error" in col for _, col in cols)


@pytest.mark.parametrize("role", ["resolvedesk_app", "resolvedesk_maint"])
def test_app_roles_cannot_read_the_views(app_engine, maint_engine, role):
    engine = app_engine if role == "resolvedesk_app" else maint_engine
    with engine.connect() as c:
        for view in VIEWS:
            assert not c.execute(
                text("SELECT has_table_privilege(current_user, :v, 'SELECT')"), {"v": view}
            ).scalar(), view


def test_views_not_owned_by_the_platform_role(platform_engine):  # noqa: F811
    with platform_engine.connect() as c:
        owners = c.execute(
            text("SELECT viewowner FROM pg_views WHERE viewname = ANY(:v)"), {"v": VIEWS}
        ).scalars().all()  # fmt: skip
    assert len(owners) == len(VIEWS) and ROLE not in owners
