"""Segments and cohorts: another tenant's brand or location ids are 404, never an empty 200.
UNRUN when written (no database was available)."""

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.models import Brand, Location
from app.core.tenancy import tenant_id_for
from tests.helpers import login

pytestmark = pytest.mark.isolation


def test_other_tenant_ids_are_404(api, app_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    others = [slug for slug in seeded if slug != tenant.name]
    assert others, "isolation tests need at least two tenants"
    for user in (u for u in cfg.users if u.role in ("hq_owner", "franchisee_owner")):
        headers = login(api, cfg.slug, user.email)
        for other in others:
            with tenant_session(tenant_id_for(seeded[other].slug), app_engine) as s:
                foreign = {
                    "location_id": list(s.scalars(select(Location.id))),
                    "brand_id": list(s.scalars(select(Brand.id))),
                }
            for param, ids in foreign.items():
                for i in ids:
                    for url in ("/insights/segments", "/insights/cohorts"):
                        resp = api.get(url, params={param: str(i)}, headers=headers)
                        assert resp.status_code == 404, (user.email, url, param)
                        assert resp.json() == {"detail": "not found"}
