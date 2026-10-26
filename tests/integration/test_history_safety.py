"""Reseed and loader safety around generated history, and money consistency in the DB."""

import uuid

import pytest
from sqlalchemy import delete, func, select, text

from app.core.db import tenant_session
from app.core.models import (
    COMMERCE_MODELS,
    ENGINE_MODELS,
    GROWTH_MODELS,
    Brand,
    Customer,
    LineItem,
    Location,
    Organization,
    Payment,
    Transaction,
    User,
)
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.core.tenant_loader import TenantLoadError, load_tenant_into_db
from app.core.verticals import load_pack
from simulator.load import load_history, load_refs
from tests.helpers import HISTORY_SCALE

COMMERCE_TABLES = {m.__tablename__ for m in COMMERCE_MODELS}
# Reseeding clears engine tables before commerce tables, so they may reference commerce rows.
RESEED_CLEARED = COMMERCE_TABLES | {m.__tablename__ for m in ENGINE_MODELS + GROWTH_MODELS}


def test_only_reseed_cleared_tables_reference_commerce_tables(app_engine):
    """Reseeding deletes every commerce row. A new table pointing at orders/payments (cases,
    refunds, approvals...) must not be silently wiped or block a reseed: this fails until the
    reseed path is taught about it."""
    with app_engine.connect() as conn:
        refs = conn.execute(
            text(
                "SELECT conrelid::regclass::text AS child, confrelid::regclass::text AS parent "
                "FROM pg_constraint WHERE contype = 'f'"
            )
        ).all()
    outside = [r for r in refs if r.parent in COMMERCE_TABLES and r.child not in RESEED_CLEARED]
    assert outside == []


def test_order_money_adds_up(app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        items = (
            select(LineItem.transaction_id, func.sum(LineItem.total_paise).label("item_sum"))
            .group_by(LineItem.transaction_id)
            .subquery()
        )
        paid = (
            select(Payment.transaction_id, func.sum(Payment.amount_paise).label("paid_sum"))
            .group_by(Payment.transaction_id)
            .subquery()
        )
        rows = s.execute(
            select(Transaction.total_paise, items.c.item_sum, paid.c.paid_sum)
            .join(items, items.c.transaction_id == Transaction.id)
            .join(paid, paid.c.transaction_id == Transaction.id)
        ).all()
    assert rows
    assert all(total == item_sum and paid_sum <= total for total, item_sum, paid_sum in rows)


@pytest.fixture
def restore(app_engine, maint_engine, seeded_history, tenant):
    yield seeded_history[tenant.name]
    cfg = seeded_history[tenant.name]
    pack = load_pack(cfg.vertical_pack)
    load_tenant_into_db(app_engine, cfg, pack)
    load_history(maint_engine, cfg, pack, scale=HISTORY_SCALE)


def test_removing_a_login_user_unlinks_their_customer(app_engine, restore):
    cfg = restore
    demo = next(u for u in cfg.users if u.role == "customer")
    trimmed = cfg.model_copy(deep=True)
    trimmed.users = [u for u in trimmed.users if u.email != demo.email]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == demo.email))
        customer_id = s.scalar(select(Customer.id).where(Customer.user_id == user_id))
        orders = s.scalar(select(func.count()).where(Transaction.customer_id == customer_id))

    load_tenant_into_db(app_engine, trimmed, load_pack(cfg.vertical_pack))

    with tenant_session(tid, app_engine) as s:
        assert s.get(Customer, customer_id).user_id is None
        assert (
            s.scalar(select(func.count()).where(Transaction.customer_id == customer_id)) == orders
        )


def test_removing_a_location_with_orders_fails_cleanly(app_engine, restore):
    cfg = restore
    tid = tenant_id_for(cfg.slug)
    gone = cfg.locations[-1].slug
    trimmed = cfg.model_copy(deep=True)
    trimmed.locations = [loc for loc in trimmed.locations if loc.slug != gone]
    for user in trimmed.users:
        user.locations = [slug for slug in user.locations if slug != gone]
    trimmed.settings.locations.pop(gone, None)
    for problem in trimmed.simulation.problems if trimmed.simulation else []:
        if problem.location == gone:
            problem.location = None
    if trimmed.simulation:
        trimmed.simulation.location_weights.pop(gone, None)
    if not trimmed.locations:
        trimmed.locations = [cfg.locations[0].model_copy(update={"slug": "replacement"})]

    with tenant_session(tid, app_engine) as s:
        before = s.scalar(select(func.count()).select_from(Transaction))
    with pytest.raises(TenantLoadError, match="history still reference"):
        load_tenant_into_db(app_engine, trimmed, load_pack(cfg.vertical_pack))
    with tenant_session(tid, app_engine) as s:  # rolled back: nothing half-applied
        assert s.scalar(select(func.count()).select_from(Transaction)) == before


def test_reseeding_one_tenant_never_touches_another(app_engine, maint_engine, restore, tenant):
    """Reseeding one tenant (maintenance role) must leave every other tenant untouched."""
    cfg = restore
    others = [p for p in tenant_dirs() if p.name != tenant.name]
    assert others, "needs at least two tenants"

    def counts(slug):
        with tenant_session(tenant_id_for(slug), app_engine) as s:
            return {
                m.__tablename__: s.scalar(select(func.count()).select_from(m))
                for m in COMMERCE_MODELS
            }

    before = {p.name: counts(load_tenant(p).slug) for p in others}
    assert all(c["transactions"] > 0 for c in before.values())
    load_history(maint_engine, cfg, load_pack(cfg.vertical_pack), scale=HISTORY_SCALE)
    assert {p.name: counts(load_tenant(p).slug) for p in others} == before


def test_refs_are_per_tenant_even_when_slugs_collide(app_engine, maint_engine, restore, tenant):
    """A same-slug brand/location/user in another tenant must never be picked up."""
    cfg = restore
    tid = tenant_id_for(cfg.slug)
    intruder = uuid.uuid4()
    brand, location, user = cfg.brands[0].slug, cfg.locations[0].slug, cfg.users[0].email
    with tenant_session(intruder, app_engine) as s:
        s.add(
            Organization(
                id=intruder,
                tenant_id=intruder,
                slug=f"x-{intruder.hex[:8]}",
                name="x",
                vertical_pack=cfg.vertical_pack,
            )
        )
        s.flush()
        s.add_all(
            [
                Brand(tenant_id=intruder, slug=brand, name="clone"),
                Location(tenant_id=intruder, slug=location, name="clone"),
                User(tenant_id=intruder, email=user, display_name="clone"),
            ]
        )
    try:
        with tenant_session(tid, maint_engine) as s:
            refs = load_refs(s, tid)
        with tenant_session(tid, app_engine) as s:  # RLS-bound truth for this tenant
            assert refs.brand_ids[brand] == s.scalar(select(Brand.id).where(Brand.slug == brand))
            assert refs.location_ids[location] == s.scalar(
                select(Location.id).where(Location.slug == location)
            )
            assert refs.user_ids[user] == s.scalar(select(User.id).where(User.email == user))
    finally:
        with tenant_session(intruder, maint_engine) as s:
            for model in (User, Location, Brand, Organization):
                s.execute(delete(model).where(model.tenant_id == intruder))
