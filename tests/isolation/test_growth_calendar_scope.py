"""The campaign calendar never shows or confirms another tenant's locations or campaigns."""

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.models import Location
from app.core.tenancy import tenant_id_for
from tests.helpers import login

pytestmark = pytest.mark.isolation


def test_other_tenant_location_filter_is_404(api, app_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    if not cfg.feature_flags.get("growth"):
        pytest.skip("growth is off for this tenant")
    others = [slug for slug in seeded if slug != tenant.name]
    assert others, "isolation tests need at least two tenants"
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    headers = login(api, cfg.slug, hq.email)
    assert api.get("/growth/calendar", headers=headers).status_code == 200
    for other in others:
        with tenant_session(tenant_id_for(seeded[other].slug), app_engine) as s:
            foreign = list(s.scalars(select(Location.id)))
        for location_id in foreign:
            params = {"location_id": str(location_id)}
            resp = api.get("/growth/calendar", params=params, headers=headers)
            assert resp.status_code == 404
            assert resp.json() == {"detail": "not found"}
