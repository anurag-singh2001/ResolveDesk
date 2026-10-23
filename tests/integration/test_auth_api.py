import pytest

from app.config import get_settings
from tests.helpers import login


def test_every_seeded_user_can_log_in(api, seeded, tenant):
    cfg = seeded[tenant.name]
    for user in cfg.users:
        me = api.get("/me", headers=login(api, cfg.slug, user.email))
        assert me.status_code == 200
        assert me.json()["role"] == user.role


@pytest.mark.parametrize(
    "field,value",
    [("password", "wrong"), ("email", "nobody@example.test"), ("tenant", "no_such_tenant")],
)
def test_bad_credentials_get_the_same_401(api, seeded, tenant, field, value):
    cfg = seeded[tenant.name]
    body = {
        "tenant": cfg.slug,
        "email": cfg.users[0].email,
        "password": get_settings().demo_password,
    }
    body[field] = value
    resp = api.post("/auth/login", json=body)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid credentials"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-token"}])
def test_protected_routes_need_a_valid_token(api, headers):
    assert api.get("/me", headers=headers).status_code == 401


def test_customer_cannot_use_staff_routes(api, seeded, tenant):
    cfg = seeded[tenant.name]
    customer = next(u for u in cfg.users if u.role == "customer")
    assert api.get("/locations", headers=login(api, cfg.slug, customer.email)).status_code == 403
