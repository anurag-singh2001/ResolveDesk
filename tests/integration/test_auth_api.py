import uuid

import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.core.auth import issue_token
from app.core.db import tenant_session
from app.core.models import Membership, User
from app.core.tenancy import tenant_id_for
from app.core.tenant_loader import load_tenant_into_db
from app.core.verticals import load_pack
from tests.helpers import login


def _body(cfg, **overrides):
    body = {
        "tenant": cfg.slug,
        "email": cfg.users[0].email,
        "password": get_settings().demo_password,
    }
    return body | overrides


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
        {"email": "nobody@example.test"},
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
