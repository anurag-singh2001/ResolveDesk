"""Order visibility over the API: location, brand and customer-ownership scope, plus tenants."""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import tenant_session
from app.core.models import (
    Brand,
    Customer,
    Location,
    Membership,
    MembershipBrand,
    Transaction,
    User,
)
from app.core.tenancy import TenantContext, tenant_id_for
from app.core.tenant_loader import load_tenant_into_db
from app.core.verticals import load_pack
from tests.helpers import login

pytestmark = pytest.mark.isolation
LIMIT = 200


def _orders(engine, slug):
    """All of a tenant's orders as (id, location_slug, brand_id, owner user_id)."""
    with tenant_session(tenant_id_for(slug), engine) as s:
        return s.execute(
            select(Transaction.id, Location.slug, Transaction.brand_id, Customer.user_id)
            .join(Location, Location.id == Transaction.location_id)
            .join(Customer, Customer.id == Transaction.customer_id)
        ).all()


def _user_id(engine, slug, email):
    with tenant_session(tenant_id_for(slug), engine) as s:
        return s.scalar(select(User.id).where(User.email == email))


def _expected(engine, cfg, user):
    orders = _orders(engine, cfg.slug)
    if user.role == "customer":
        uid = _user_id(engine, cfg.slug, user.email)
        return {o.id for o in orders if o.user_id == uid}
    if user.role == "hq_owner":
        return {o.id for o in orders}
    return {o.id for o in orders if o.slug in user.locations}


def test_each_user_sees_exactly_their_orders(api, app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    all_ids = {o.id for o in _orders(app_engine, cfg.slug)}
    for user in cfg.users:
        headers = login(api, cfg.slug, user.email)
        expected = _expected(app_engine, cfg, user)
        listed = api.get(f"/orders?limit={LIMIT}", headers=headers).json()
        listed_ids = {o["id"] for o in listed}
        assert {str(i) for i in expected} >= listed_ids, user.email
        assert len(listed) == min(LIMIT, len(expected)), user.email

        hidden = all_ids - expected
        for order_id in list(expected)[:3]:
            assert api.get(f"/orders/{order_id}", headers=headers).status_code == 200
        for order_id in list(hidden)[:3]:
            resp = api.get(f"/orders/{order_id}", headers=headers)
            assert resp.status_code == 404, (user.email, order_id)


def test_customers_have_orders_to_see(api, app_engine, seeded_history, tenant):
    """Guards the test above: demo customers must actually own orders."""
    cfg = seeded_history[tenant.name]
    for user in (u for u in cfg.users if u.role == "customer"):
        assert _expected(app_engine, cfg, user), user.email


def test_other_tenant_orders_are_404(api, app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    headers = login(api, cfg.slug, hq.email)
    for other in (slug for slug in seeded_history if slug != tenant.name):
        for order in _orders(app_engine, seeded_history[other].slug)[:10]:
            resp = api.get(f"/orders/{order.id}", headers=headers)
            assert resp.status_code == 404
            assert resp.json() == {"detail": "not found"}


def test_brand_scope_narrows_orders(api, app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    candidates = [
        (u, loc)
        for u in cfg.users
        if u.locations
        for loc in cfg.locations
        if loc.slug in u.locations and len(loc.brands) > 1
    ]
    if not candidates:
        pytest.skip("no scoped user at a multi-brand location in this tenant")
    user, loc = candidates[0]
    tid = tenant_id_for(cfg.slug)
    try:
        with tenant_session(tid, app_engine) as s:
            keep = s.scalar(select(Brand.id).where(Brand.slug == loc.brands[0]))
            membership_id = s.scalar(
                select(Membership.id)
                .join(User, User.id == Membership.user_id)
                .where(User.email == user.email)
            )
            s.add(MembershipBrand(tenant_id=tid, membership_id=membership_id, brand_id=keep))
        headers = login(api, cfg.slug, user.email)
        orders = _orders(app_engine, cfg.slug)
        expected = {str(o.id) for o in orders if o.slug in user.locations and o.brand_id == keep}
        listed = {o["id"] for o in api.get(f"/orders?limit={LIMIT}", headers=headers).json()}
        assert listed and listed <= expected
        other_brand = next(o for o in orders if o.slug in user.locations and o.brand_id != keep)
        assert api.get(f"/orders/{other_brand.id}", headers=headers).status_code == 404
    finally:
        load_tenant_into_db(app_engine, cfg, load_pack(cfg.vertical_pack))
    with tenant_session(tid, app_engine) as s:  # shared session data is back to the folder
        assert s.scalar(select(func.count()).select_from(MembershipBrand)) == sum(
            len(u.brands) for u in cfg.users
        )


@pytest.mark.parametrize("role", ["hq_owner", "location_manager", "franchisee_owner"])
def test_visible_orders_brand_and_location_rules(app_engine, seeded_history, tenant, role):
    """Runs the predicate directly with synthetic contexts, so it is proven for every tenant
    (including single-brand ones) without changing shared data."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        orders = s.execute(select(Transaction.id, Transaction.location_id, Transaction.brand_id))
        orders = orders.all()
        first = orders[0]
        locations = frozenset() if role == "hq_owner" else frozenset({first.location_id})

        def visible(brands):
            ctx = TenantContext(tid, uuid.uuid4(), uuid.uuid4(), role, brands, locations)
            return set(s.scalars(select(Transaction.id).where(ctx.visible_orders())))

        in_scope = {
            o.id for o in orders if role == "hq_owner" or o.location_id == first.location_id
        }
        assert visible(frozenset()) == in_scope
        assert visible(frozenset({first.brand_id})) == {
            o.id for o in orders if o.id in in_scope and o.brand_id == first.brand_id
        }
        assert visible(frozenset({uuid.uuid4()})) == set()  # unknown brand: nothing


def test_customer_cannot_see_orders_of_a_customer_sharing_their_phone(
    api, app_engine, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    user = next(u for u in cfg.users if u.role == "customer")
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == user.email))
        mine = s.scalar(select(Customer).where(Customer.user_id == user_id))
        other = s.scalar(
            select(Customer)
            .join(Transaction, Transaction.customer_id == Customer.id)
            .where(Customer.id != mine.id, Customer.user_id.is_(None))
            .limit(1)
        )
        other_id, original_phone = other.id, other.phone
        other.phone = mine.phone  # messy data: two customers, one phone number
        other_order = s.scalar(select(Transaction.id).where(Transaction.customer_id == other.id))
    try:
        headers = login(api, cfg.slug, user.email)
        listed = {o["id"] for o in api.get(f"/orders?limit={LIMIT}", headers=headers).json()}
        assert str(other_order) not in listed
        assert api.get(f"/orders/{other_order}", headers=headers).status_code == 404
    finally:
        with tenant_session(tid, app_engine) as s:
            s.get(Customer, other_id).phone = original_phone
