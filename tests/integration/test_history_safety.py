"""Reseed and loader safety around generated history, and money consistency in the DB."""

import pytest
from sqlalchemy import func, select, text

from app.core.db import tenant_session
from app.core.models import (
    COMMERCE_MODELS,
    ENGINE_MODELS,
    Customer,
    LineItem,
    Payment,
    Transaction,
    User,
)
from app.core.tenancy import tenant_id_for
from app.core.tenant_loader import TenantLoadError, load_tenant_into_db
from app.core.verticals import load_pack
from simulator.load import load_history
from tests.helpers import HISTORY_SCALE

COMMERCE_TABLES = {m.__tablename__ for m in COMMERCE_MODELS}
# Reseeding clears engine tables before commerce tables, so they may reference commerce rows.
RESEED_CLEARED = COMMERCE_TABLES | {m.__tablename__ for m in ENGINE_MODELS}


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
def restore(app_engine, seeded_history, tenant):
    yield seeded_history[tenant.name]
    cfg = seeded_history[tenant.name]
    pack = load_pack(cfg.vertical_pack)
    load_tenant_into_db(app_engine, cfg, pack)
    load_history(app_engine, cfg, pack, scale=HISTORY_SCALE)


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
