"""Platform admin (S9.1): a separate principal and a DB role that can read only aggregates.

Tests never name a tenant: the tenants fixture makes two fresh ones, and tenant-user tests
run over every folder under tenants/.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import ProgrammingError

from app.api.deps import get_db_engine
from app.api.routes_platform import get_platform_engine
from app.config import DEV_JWT_SECRET, get_settings
from app.core.auth import AuthError
from app.core.db import ENGINE_OPTIONS, tenant_session
from app.core.models import Organization
from app.core.passwords import hash_password
from app.core.platform_auth import PlatformLocked, authenticate_platform, reset_failures
from app.main import create_app
from tests.helpers import login

pytestmark = pytest.mark.isolation

ROLE = "resolvedesk_platform"
EMAIL = "operator@example.test"
PLATFORM_SECRET = "platform-only-secret-platform-only-secret-1"
PASSWORD = "correct horse battery staple"
VIEWS = [
    "platform_tenants_v",
    "platform_case_counts_v",
    "platform_approval_counts_v",
    "platform_activity_v",
]
# Anything that could carry a person, a message or a row identity must never be a column.
FORBIDDEN_FRAGMENTS = (
    "name", "phone", "email", "address", "message", "body", "text", "note", "content",
    "customer", "line", "item", "sku", "ref", "payload", "token", "password", "user",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _clean_settings():
    get_settings.cache_clear()
    reset_failures()
    yield
    get_settings.cache_clear()
    reset_failures()


@pytest.fixture
def platform_env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAIL", EMAIL)
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=4))
    monkeypatch.setenv("PLATFORM_DATABASE_URL", "postgresql://unused.invalid/unused")
    monkeypatch.setenv("PLATFORM_JWT_SECRET", PLATFORM_SECRET)
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def platform_engine(app_engine):
    """The platform role on the test database. The owner switches into it (SET ROLE) so the
    test needs no password; every privilege below is the role's, not the owner's."""
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
def papi(app_engine, platform_engine, platform_env) -> TestClient:
    application = create_app()
    application.dependency_overrides[get_db_engine] = lambda: app_engine
    application.dependency_overrides[get_platform_engine] = lambda: platform_engine
    return TestClient(application)


def _platform_headers(client: TestClient) -> dict[str, str]:
    resp = client.post("/platform/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _slugs(app_engine, tenant) -> str:
    with tenant_session(tenant.tenant_id, app_engine) as s:
        return s.query(Organization.slug).scalar()


# ---- off by default / fail closed ------------------------------------------------------


def test_routes_are_404_when_not_configured(app_engine, monkeypatch):
    for name in ("PLATFORM_ADMIN_EMAIL", "PLATFORM_ADMIN_PASSWORD_HASH", "PLATFORM_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert (
        client.post("/platform/auth/login", json={"email": "a", "password": "b"}).status_code == 404
    )
    assert client.get("/platform/tenants").status_code == 404
    assert client.get("/platform/tenants", headers={"Authorization": "Bearer x"}).status_code == 404


@pytest.mark.parametrize(
    "missing",
    [
        "PLATFORM_JWT_SECRET",
        "PLATFORM_ADMIN_EMAIL",
        "PLATFORM_ADMIN_PASSWORD_HASH",
        "PLATFORM_DATABASE_URL",
    ],
)
def test_any_missing_setting_keeps_it_off(platform_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/platform/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 404


def test_blank_settings_keep_it_off(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAIL", "  ")
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD_HASH", "")
    monkeypatch.setenv("PLATFORM_DATABASE_URL", "postgresql://unused.invalid/unused")
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert (
        client.post("/platform/auth/login", json={"email": " ", "password": ""}).status_code == 404
    )


# ---- login and token separation --------------------------------------------------------


def test_login_wrong_credentials_are_401_and_locks_out(papi):
    bad = {"email": EMAIL, "password": "nope"}
    assert (
        papi.post(
            "/platform/auth/login", json={"email": "x@example.test", "password": PASSWORD}
        ).status_code
        == 401
    )
    for _ in range(4):
        assert papi.post("/platform/auth/login", json=bad).status_code == 401
    # Five failures: even the right password is refused until the window passes.
    assert (
        papi.post("/platform/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code
        == 429
    )


def test_platform_token_has_no_tenant_and_its_own_type(papi):
    import jwt

    token = _platform_headers(papi)["Authorization"].split()[1]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert "tid" not in claims
    assert claims["typ"] == "platform_admin"
    assert claims["aud"] != get_settings().jwt_audience


def test_platform_routes_need_a_token(papi):
    assert papi.get("/platform/tenants").status_code == 401
    assert (
        papi.get("/platform/tenants", headers={"Authorization": "Bearer junk"}).status_code == 401
    )


def test_tenant_user_cannot_call_platform_routes(papi, seeded, tenant):
    cfg = seeded[tenant.name]
    for user in cfg.users:
        headers = login(papi, cfg.slug, user.email)
        for path in ("tenants", "cases", "approvals", "activity"):
            assert papi.get(f"/platform/{path}", headers=headers).status_code == 403, user.email


def test_platform_token_cannot_call_tenant_routes(papi, seeded):
    headers = _platform_headers(papi)
    for path in ("/locations", "/cases", "/approvals", "/me"):
        assert papi.get(path, headers=headers).status_code == 401, path


# ---- aggregates ------------------------------------------------------------------------


def test_both_tenants_appear_in_every_aggregate(papi, app_engine, tenants):
    a, b = tenants
    slugs = {_slugs(app_engine, a), _slugs(app_engine, b)}
    headers = _platform_headers(papi)
    listed = {r["tenant_slug"] for r in papi.get("/platform/tenants", headers=headers).json()}
    assert slugs <= listed
    cases = papi.get("/platform/cases", headers=headers).json()
    assert slugs <= {r["tenant_slug"] for r in cases}
    assert all(r["case_count"] >= 1 for r in cases)
    approvals = papi.get("/platform/approvals", headers=headers).json()
    assert slugs <= {r["tenant_slug"] for r in approvals}
    activity = papi.get("/platform/activity", headers=headers).json()
    assert slugs <= {r["tenant_slug"] for r in activity}


def test_aggregate_counts_match_the_tenant_own_data(papi, app_engine, tenants):
    a, _ = tenants
    slug = _slugs(app_engine, a)
    with tenant_session(a.tenant_id, app_engine) as s:
        own = s.execute(text("SELECT count(*) FROM cases")).scalar()
    rows = papi.get("/platform/cases", headers=_platform_headers(papi)).json()
    assert sum(r["case_count"] for r in rows if r["tenant_slug"] == slug) == own


def test_reads_write_an_audit_event_with_no_content(papi, owner_engine):
    headers = _platform_headers(papi)
    with owner_engine.connect() as c:
        before = c.execute(text("SELECT count(*) FROM platform_audit_events")).scalar()
    assert papi.get("/platform/tenants", headers=headers).status_code == 200
    with owner_engine.connect() as c:
        after = c.execute(text("SELECT count(*) FROM platform_audit_events")).scalar()
        row = c.execute(
            text("SELECT actor, route FROM platform_audit_events ORDER BY occurred_at DESC LIMIT 1")
        ).one()
        cols = c.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'platform_audit_events'"
            )
        ).scalars().all()  # fmt: skip
    assert after == before + 1
    assert tuple(row) == ("platform_admin", "GET /platform/tenants")
    assert sorted(cols) == ["actor", "id", "occurred_at", "route"]


def test_failed_login_and_denied_calls_write_no_platform_audit(papi, owner_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    user = cfg.users[0]
    with owner_engine.connect() as c:
        before = c.execute(text("SELECT count(*) FROM platform_audit_events")).scalar()
    papi.get("/platform/tenants", headers=login(papi, cfg.slug, user.email))
    papi.get("/platform/tenants")
    with owner_engine.connect() as c:
        after = c.execute(text("SELECT count(*) FROM platform_audit_events")).scalar()
    assert after == before


# ---- the DB role -----------------------------------------------------------------------


def test_platform_role_attributes(platform_engine):
    with platform_engine.connect() as c:
        who = c.execute(text("SELECT current_user")).scalar()
        attrs = c.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolinherit "
                "FROM pg_roles WHERE rolname = :r"
            ),
            {"r": ROLE},
        ).one()
    assert who == ROLE
    assert tuple(attrs) == (False, False, False, False, False)


def test_platform_role_has_no_privilege_on_any_table(platform_engine):
    with platform_engine.connect() as c:
        granted = c.execute(
            text(
                """
                SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('public', 'lg') AND c.relkind IN ('r', 'p')
                  AND (has_table_privilege(:r, c.oid, 'SELECT')
                       OR has_table_privilege(:r, c.oid, 'INSERT')
                       OR has_table_privilege(:r, c.oid, 'UPDATE')
                       OR has_table_privilege(:r, c.oid, 'DELETE'))
                """
            ),
            {"r": ROLE},
        ).scalars().all()  # fmt: skip
    assert granted == []


@pytest.mark.parametrize(
    "table", ["cases", "customers", "ticket_messages", "users", "audit_events", "organizations",
              "platform_audit_events", "approvals"],
)  # fmt: skip
def test_platform_role_cannot_select_raw_tables(platform_engine, table):
    with platform_engine.connect() as c, pytest.raises(ProgrammingError, match="permission denied"):
        c.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


def test_platform_role_cannot_write_or_set_a_tenant(platform_engine):
    with platform_engine.connect() as c, pytest.raises(ProgrammingError, match="permission denied"):
        c.execute(text("DELETE FROM platform_audit_events"))
    with platform_engine.connect() as c, pytest.raises(ProgrammingError, match="permission denied"):
        c.execute(text("CREATE TABLE platform_probe (x int)"))
    # A tenant setting changes nothing: the views already span tenants and raw tables stay shut.
    with platform_engine.connect() as c:
        c.execute(text("SELECT set_config('app.tenant_id', gen_random_uuid()::text, true)"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            c.execute(text("SELECT 1 FROM cases LIMIT 1"))


@pytest.mark.parametrize("role", ["resolvedesk_app", "resolvedesk_maint"])
def test_app_roles_cannot_touch_platform_objects(app_engine, maint_engine, role):
    engine = app_engine if role == "resolvedesk_app" else maint_engine
    with engine.connect() as c:
        for view in VIEWS:
            assert not c.execute(
                text("SELECT has_table_privilege(current_user, :v, 'SELECT')"), {"v": view}
            ).scalar(), view
        assert not c.execute(
            text("SELECT has_table_privilege(current_user, 'platform_audit_events', 'SELECT')")
        ).scalar()
        assert not c.execute(
            text(
                "SELECT has_function_privilege(current_user, "
                "'platform_audit_record(text, text)', 'EXECUTE')"
            )
        ).scalar()


def test_views_expose_only_aggregate_columns(platform_engine):
    with platform_engine.connect() as c:
        cols = c.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_name = ANY(:v)"
            ),
            {"v": VIEWS},
        ).all()
    assert {t for t, _ in cols} == set(VIEWS)
    bad = [(t, col) for t, col in cols if any(f in col for f in FORBIDDEN_FRAGMENTS)]
    assert bad == []
    # The only row-level-looking column allowed is none: no id of any kind.
    assert [(t, col) for t, col in cols if col == "id" or col.endswith("_id")] == []


def test_views_are_owned_by_someone_other_than_the_platform_role(platform_engine):
    with platform_engine.connect() as c:
        owners = c.execute(
            text("SELECT viewowner FROM pg_views WHERE viewname = ANY(:v)"), {"v": VIEWS}
        ).scalars().all()  # fmt: skip
    assert len(owners) == len(VIEWS)
    assert ROLE not in owners


# ---- review fixes: secret separation, lockout race, role guard --------------------------


def _forged(secret: str) -> dict[str, str]:
    now = datetime.now(UTC)
    claims = {
        "sub": "platform_admin",
        "typ": "platform_admin",
        "iss": get_settings().jwt_issuer,
        "aud": get_settings().platform_jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}


def test_platform_token_forged_with_tenant_or_dev_secret_is_rejected(papi):
    for secret in (get_settings().jwt_secret, DEV_JWT_SECRET):
        assert papi.get("/platform/tenants", headers=_forged(secret)).status_code == 401
    assert papi.get("/platform/tenants", headers=_forged(PLATFORM_SECRET)).status_code == 200


@pytest.mark.parametrize("secret", ["short", DEV_JWT_SECRET, "same-as-tenant"])
def test_weak_or_shared_platform_secret_keeps_it_off(platform_env, monkeypatch, secret):
    if secret == "same-as-tenant":
        secret = "x" * 40
        monkeypatch.setenv("JWT_SECRET", secret)
    monkeypatch.setenv("PLATFORM_JWT_SECRET", secret)
    get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.post("/platform/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 404


def test_parallel_guesses_cannot_outrun_the_lockout(platform_env):
    outcomes: list[str] = []
    gate = threading.Barrier(12)

    def guess():
        gate.wait()
        try:
            authenticate_platform(EMAIL, "wrong")
            outcomes.append("ok")
        except PlatformLocked:
            outcomes.append("locked")
        except AuthError:
            outcomes.append("bad")

    threads = [threading.Thread(target=guess) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("bad") == 5
    assert outcomes.count("locked") == 7


def test_correct_login_gives_its_slot_back(platform_env):
    for _ in range(3):
        assert authenticate_platform(EMAIL, PASSWORD).token
    for _ in range(5):
        with pytest.raises(AuthError):
            authenticate_platform(EMAIL, "wrong")


def test_failed_login_is_logged_without_the_credentials(papi, caplog):
    # alembic's fileConfig (run by the app_engine fixture) disables existing loggers.
    logging.getLogger("app.core.platform_auth").disabled = False
    with caplog.at_level("WARNING"):
        papi.post("/platform/auth/login", json={"email": EMAIL, "password": "secret-guess"})
    text_ = " ".join(r.getMessage() for r in caplog.records)
    assert "platform login failed" in text_
    assert "secret-guess" not in text_
    assert EMAIL not in text_


def test_connection_not_on_the_platform_role_fails_closed(app_engine, platform_env, owner_engine):
    application = create_app()
    application.dependency_overrides[get_platform_engine] = lambda: app_engine
    client = TestClient(application)
    resp = client.get("/platform/tenants", headers=_platform_headers(client))
    assert resp.status_code == 503


def test_app_role_cannot_call_the_audit_function(app_engine):
    with app_engine.connect() as c, pytest.raises(ProgrammingError, match="permission denied"):
        c.execute(text("SELECT platform_audit_record('a', 'b')"))


def test_audit_table_rejects_empty_actor_or_route(owner_engine):
    for actor, route in (("", "r"), ("a", "")):
        with owner_engine.begin() as c, pytest.raises(Exception, match="check"):  # noqa: B017
            c.execute(
                text("INSERT INTO platform_audit_events (actor, route) VALUES (:a, :r)"),
                {"a": actor, "r": route},
            )


def test_downgrade_then_upgrade_restores_exactly_the_same_rights(app_engine):
    """Run last: it drops and recreates the platform objects on the test database."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.attributes["url"] = get_settings().test_migration_database_url
    command.downgrade(cfg, "0027")
    with app_engine.connect() as c:
        assert not c.execute(
            text("SELECT to_regclass('platform_audit_events') IS NOT NULL")
        ).scalar()
    command.upgrade(cfg, "head")
    eng = create_engine(get_settings().test_migration_database_url, **ENGINE_OPTIONS)
    with eng.connect() as c:
        views = c.execute(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee = :r AND privilege_type = 'SELECT' AND table_name = ANY(:v)"
            ),
            {"r": ROLE, "v": VIEWS},
        ).scalar()
        raw = c.execute(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee = :r AND table_name <> ALL(:v)"
            ),
            {"r": ROLE, "v": VIEWS},
        ).scalar()
    eng.dispose()
    assert (views, raw) == (len(VIEWS), 0)
