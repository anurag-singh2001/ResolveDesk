"""Isolation matrix over the API: every staff user vs every location of every tenant."""

import pytest
from sqlalchemy import select

from app.core.auth import issue_token
from app.core.db import tenant_session
from app.core.models import Location, User
from app.core.tenancy import tenant_id_for
from tests.helpers import login

pytestmark = pytest.mark.isolation


def _location_ids(engine, slug):
    with tenant_session(tenant_id_for(slug), engine) as s:
        return dict(s.execute(select(Location.slug, Location.id)).all())


def test_staff_see_exactly_their_scope(api, app_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    own = _location_ids(app_engine, cfg.slug)
    for user in (u for u in cfg.users if u.role != "customer"):
        headers = login(api, cfg.slug, user.email)
        allowed = set(own) if user.role == "hq_owner" else set(user.locations)

        listed = {loc["slug"] for loc in api.get("/locations", headers=headers).json()}
        assert listed == allowed, user.email

        for slug, location_id in own.items():
            resp = api.get(f"/locations/{location_id}", headers=headers)
            assert resp.status_code == (200 if slug in allowed else 404), (user.email, slug)


def test_other_tenant_locations_are_404(api, app_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    others = [slug for slug in seeded if slug != tenant.name]
    assert others, "isolation tests need at least two tenants"
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    headers = login(api, cfg.slug, hq.email)
    for other in others:
        for location_id in _location_ids(app_engine, seeded[other].slug).values():
            resp = api.get(f"/locations/{location_id}", headers=headers)
            assert resp.status_code == 404
            assert resp.json() == {"detail": "not found"}


def test_token_naming_another_tenant_is_rejected(api, app_engine, seeded, tenant):
    """A user id is only valid inside its own tenant: a forged tid gets 401, not data."""
    cfg = seeded[tenant.name]
    other = next(slug for slug in seeded if slug != tenant.name)
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        user_id = s.scalars(select(User.id)).first()
    forged = issue_token(tenant_id_for(seeded[other].slug), user_id)
    resp = api.get("/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
