"""The request's role and scope come from the DB in one round trip, and fail closed."""

import uuid

import pytest
from sqlalchemy import event, select

from app.core.db import tenant_session
from app.core.models import Brand, Location, User
from app.core.tenancy import load_context, tenant_id_for

pytestmark = pytest.mark.isolation


def test_every_user_gets_their_configured_role_and_scope_in_one_query(app_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        users = dict(s.execute(select(User.email, User.id)).all())
        brand_ids = dict(s.execute(select(Brand.slug, Brand.id)).all())
        location_ids = dict(s.execute(select(Location.slug, Location.id)).all())
    queries = []

    def count(conn, cursor, statement, *args):
        queries.append(statement)

    event.listen(app_engine, "before_cursor_execute", count)
    try:
        for user in cfg.users:
            with tenant_session(tid, app_engine) as s:
                queries.clear()
                ctx = load_context(s, tid, users[user.email])
                assert len(queries) == 1, queries
            assert ctx.role == user.role
            assert ctx.brand_ids == {brand_ids[b] for b in user.brands}
            assert ctx.location_ids == {location_ids[loc] for loc in user.locations}
    finally:
        event.remove(app_engine, "before_cursor_execute", count)


def test_another_tenants_user_or_an_unknown_id_gets_no_context(app_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    tid = tenant_id_for(cfg.slug)
    others = [c for name, c in seeded.items() if name != tenant.name]
    assert others, "needs a second tenant"
    other = others[0]
    with tenant_session(tenant_id_for(other.slug), app_engine) as s:
        foreign_user = s.scalar(select(User.id).limit(1))
    with tenant_session(tid, app_engine) as s:
        assert load_context(s, tid, foreign_user) is None  # invisible under this tenant's RLS
        assert load_context(s, tid, uuid.uuid4()) is None


class _RollBack(Exception):
    pass


def test_a_user_without_a_membership_gets_no_context(app_engine, seeded, tenant):
    tid = tenant_id_for(seeded[tenant.name].slug)
    # Raising rolls the transaction back: nothing written stays.
    with pytest.raises(_RollBack), tenant_session(tid, app_engine) as s:
        user = User(tenant_id=tid, email="no-role@example.test", display_name="No role")
        s.add(user)
        s.flush()
        assert load_context(s, tid, user.id) is None
        raise _RollBack
