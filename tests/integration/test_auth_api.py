import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update

from app.api.deps import get_clock, get_db_engine, get_tenant_context, tenant_db
from app.config import get_settings
from app.core.auth import issue_token
from app.core.db import tenant_session
from app.core.models import LoginFailure, Membership, User
from app.core.tenancy import tenant_id_for
from app.core.tenant_loader import load_tenant_into_db
from app.core.verticals import load_pack
from app.main import create_app
from tests.helpers import demo_password, login

UNKNOWN = "<unknown email>"  # replaced per test by a fresh address (lockout counts persist)


def _body(cfg, **overrides):
    email = overrides.pop("email", cfg.users[0].email)
    if email == UNKNOWN:
        email = f"nobody-{uuid.uuid4().hex[:12]}@example.test"
    body = {
        "tenant": cfg.slug,
        "email": email,
        "password": demo_password(cfg.slug, cfg.users[0].email),
    }
    return body | overrides


@pytest.fixture(autouse=True)
def clear_login_failures(app_engine, seeded):
    """Failed logins in this module must not lock demo users out for the rest of the run."""
    yield
    for cfg in seeded.values():
        with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
            s.execute(delete(LoginFailure))


def test_every_seeded_user_can_log_in(api, seeded, tenant):
    cfg = seeded[tenant.name]
    for user in cfg.users:
        me = api.get("/me", headers=login(api, cfg.slug, user.email))
        assert me.status_code == 200
        assert me.json()["role"] == user.role


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": "wrong"},
        {"email": UNKNOWN},
        {"tenant": "no_such_tenant"},
        {"tenant": "Not A Slug!"},
    ],
)
def test_bad_credentials_get_the_same_401(api, seeded, tenant, overrides):
    resp = api.post("/auth/login", json=_body(seeded[tenant.name], **overrides))
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid credentials"}


def test_email_from_another_tenant_gets_the_same_401(api, seeded, tenant):
    cfg = seeded[tenant.name]
    own = {u.email for u in cfg.users}
    foreign = next(
        u.email
        for slug, other in seeded.items()
        if slug != tenant.name
        for u in other.users
        if u.email not in own
    )
    resp = api.post("/auth/login", json=_body(cfg, email=foreign))
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid credentials"}


@pytest.mark.parametrize("path", ["/me", "/locations", f"/locations/{uuid.uuid4()}"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-token"}])
def test_protected_routes_need_a_valid_token(api, path, headers):
    assert api.get(path, headers=headers).status_code == 401


def test_token_for_unknown_user_is_rejected(api, seeded, tenant):
    token = issue_token(tenant_id_for(seeded[tenant.name].slug), uuid.uuid4())
    assert api.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_customer_cannot_use_staff_routes(api, seeded, tenant):
    cfg = seeded[tenant.name]
    customer = next(u for u in cfg.users if u.role == "customer")
    headers = login(api, cfg.slug, customer.email)
    assert api.get("/locations", headers=headers).status_code == 403
    assert api.get(f"/locations/{uuid.uuid4()}", headers=headers).status_code == 403


def test_context_and_route_data_share_one_transaction(app_engine, seeded, tenant):
    """The access decision and the data a route reads must come from the same transaction."""

    application = create_app()
    application.dependency_overrides[get_db_engine] = lambda: app_engine

    @application.get("/_probe")
    def probe(ctx=Depends(get_tenant_context), db=Depends(tenant_db)):
        return {
            "same_session": db.info.get("ctx") is ctx,
            "txid": db.execute(text("SELECT txid_current()")).scalar(),
            "txid_again": db.execute(text("SELECT txid_current()")).scalar(),
        }

    client = TestClient(application)
    cfg = seeded[tenant.name]
    body = client.get("/_probe", headers=login(client, cfg.slug, cfg.users[0].email)).json()
    assert body["same_session"] is True
    assert body["txid"] == body["txid_again"]


@pytest.fixture
def restore_tenant(app_engine, seeded, tenant):
    """Tests below change membership rows; the folder reload puts them back."""
    yield
    cfg = seeded[tenant.name]
    load_tenant_into_db(app_engine, cfg, load_pack(cfg.vertical_pack))


def test_role_change_applies_to_existing_token(api, app_engine, seeded, tenant, restore_tenant):
    cfg = seeded[tenant.name]
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    headers = login(api, cfg.slug, hq.email)
    assert api.get("/locations", headers=headers).status_code == 200

    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == hq.email))
        s.execute(update(Membership).where(Membership.user_id == user_id).values(role="customer"))

    assert api.get("/me", headers=headers).json()["role"] == "customer"
    assert api.get("/locations", headers=headers).status_code == 403


def test_user_without_membership_is_rejected(api, app_engine, seeded, tenant, restore_tenant):
    cfg = seeded[tenant.name]
    user = cfg.users[0]
    headers = login(api, cfg.slug, user.email)
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == user.email))
        s.execute(Membership.__table__.delete().where(Membership.user_id == user_id))

    assert api.get("/me", headers=headers).status_code == 401
    assert api.post("/auth/login", json=_body(cfg, email=user.email)).status_code == 401


def test_login_returns_the_token_expiry(api, seeded, tenant):
    cfg = seeded[tenant.name]
    before = datetime.now(UTC)
    resp = api.post("/auth/login", json=_body(cfg))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    expires_at = datetime.fromisoformat(body["expires_at"])
    ttl = timedelta(minutes=get_settings().jwt_ttl_minutes)
    assert before + ttl - timedelta(minutes=1) <= expires_at <= before + ttl + timedelta(minutes=1)


def test_passwords_are_stored_as_bcrypt_hashes(app_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        stored = dict(s.execute(select(User.email, User.password_hash)).all())
    for user in cfg.users:
        assert stored[user.email].startswith("$2"), user.email
        assert cfg.demo_password_for(user) not in stored[user.email]


def test_wrong_password_and_unknown_user_look_the_same(api, seeded, tenant):
    cfg = seeded[tenant.name]
    wrong = api.post("/auth/login", json=_body(cfg, password="not-the-password"))
    unknown = api.post("/auth/login", json=_body(cfg, email=UNKNOWN))
    assert (wrong.status_code, wrong.json()) == (unknown.status_code, unknown.json())
    assert wrong.status_code == 401


@pytest.fixture
def clock_api(app_engine, seeded):
    """API client whose clock the test sets (for the lockout window)."""
    application = create_app()
    application.dependency_overrides[get_db_engine] = lambda: app_engine
    clock = {"now": datetime.now(UTC)}
    application.dependency_overrides[get_clock] = lambda: clock["now"]
    return TestClient(application), clock


@pytest.mark.parametrize("who", ["known", "unknown"])
def test_lockout_after_repeated_failures_then_ok_after_the_window(clock_api, seeded, tenant, who):
    client, clock = clock_api
    cfg = seeded[tenant.name]
    s = get_settings()
    body = _body(cfg) if who == "known" else _body(cfg, email=UNKNOWN)
    for _ in range(s.login_max_failures):
        resp = client.post("/auth/login", json=body | {"password": "wrong-password"})
        assert resp.status_code == 401
    # Locked: even the right password gets 429, and an unknown email locks the same way,
    # so a 429 doesn't reveal that an account exists. Case and spaces don't reset it.
    assert client.post("/auth/login", json=body).status_code == 429
    shouted = body | {"email": "  " + body["email"].upper()}
    assert client.post("/auth/login", json=shouted).status_code == 429

    clock["now"] += timedelta(minutes=s.login_window_minutes, seconds=1)
    expected = 200 if who == "known" else 401
    assert client.post("/auth/login", json=body).status_code == expected


def test_success_clears_earlier_failures(clock_api, seeded, tenant):
    client, _ = clock_api
    cfg = seeded[tenant.name]
    s = get_settings()
    for _ in range(2):
        for _ in range(s.login_max_failures - 1):
            client.post("/auth/login", json=_body(cfg, password="wrong-password"))
        assert client.post("/auth/login", json=_body(cfg)).status_code == 200


def test_lockout_is_per_tenant(clock_api, seeded, tenant):
    """Failures in one tenant never lock a user in another tenant."""
    client, _ = clock_api
    cfg = seeded[tenant.name]
    for _ in range(get_settings().login_max_failures):
        client.post("/auth/login", json=_body(cfg, password="wrong-password"))
    assert client.post("/auth/login", json=_body(cfg)).status_code == 429
    for other in (c for c in seeded.values() if c.slug != cfg.slug):
        assert client.post("/auth/login", json=_body(other)).status_code == 200


def test_businesses_list_only_what_the_login_screen_needs(api, seeded, tenant):
    cfg = seeded[tenant.name]
    resp = api.get("/auth/businesses")
    assert resp.status_code == 200
    rows = resp.json()
    assert all(set(r) == {"slug", "name", "vertical"} for r in rows)
    mine = next(r for r in rows if r["slug"] == cfg.slug)
    assert mine == {"slug": cfg.slug, "name": cfg.name, "vertical": cfg.vertical_pack}


def test_me_includes_the_tenant(api, seeded, tenant):
    cfg = seeded[tenant.name]
    me = api.get("/me", headers=login(api, cfg.slug, cfg.users[0].email)).json()
    assert me["tenant"] == {"slug": cfg.slug, "name": cfg.name, "vertical": cfg.vertical_pack}


@pytest.fixture
def demo_off(monkeypatch, app_engine, seeded, tenant):
    """Reload the tenant with DEMO_AUTH off; reloading with it on restores the hashes."""
    import app.core.tenant_loader as loader

    cfg = seeded[tenant.name]
    off = get_settings().model_copy(update={"demo_auth": False})
    monkeypatch.setattr(loader, "get_settings", lambda: off)
    load_tenant_into_db(app_engine, cfg, load_pack(cfg.vertical_pack))
    yield cfg
    monkeypatch.undo()
    load_tenant_into_db(app_engine, cfg, load_pack(cfg.vertical_pack))


def test_demo_passwords_stop_working_when_demo_auth_is_off(api, app_engine, demo_off):
    cfg = demo_off
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        assert set(s.scalars(select(User.password_hash))) == {None}
    resp = api.post("/auth/login", json=_body(cfg))
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid credentials"}
