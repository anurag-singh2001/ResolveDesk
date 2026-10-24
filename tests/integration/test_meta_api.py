import pytest

from app.core.verticals import load_pack
from tests.helpers import login


def test_categories_are_the_callers_pack_for_every_role(api, seeded, tenant):
    cfg = seeded[tenant.name]
    expected = list(load_pack(cfg.vertical_pack).issue_categories)
    for user in cfg.users:
        resp = api.get("/meta/categories", headers=login(api, cfg.slug, user.email))
        assert resp.status_code == 200
        assert resp.json() == {"categories": expected}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-token"}])
def test_categories_need_a_valid_token(api, headers):
    assert api.get("/meta/categories", headers=headers).status_code == 401


def test_me_reports_the_logged_in_user(api, seeded, tenant):
    cfg = seeded[tenant.name]
    for user in cfg.users:
        me = api.get("/me", headers=login(api, cfg.slug, user.email)).json()
        assert (me["name"], me["email"], me["role"]) == (user.name, user.email, user.role)
