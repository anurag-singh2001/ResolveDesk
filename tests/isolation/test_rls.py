import uuid

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.db import tenant_session
from app.core.models import (
    TENANT_MODELS,
    Brand,
    LocationBrand,
    MembershipBrand,
    MembershipLocation,
    Transaction,
)
from app.engine.checkpoint import open_checkpointer

pytestmark = pytest.mark.isolation


def _by_name(m):
    return m.__tablename__


@pytest.mark.parametrize("model", TENANT_MODELS, ids=_by_name)
def test_tenant_sees_only_own_rows(app_engine, tenants, model):
    a, b = tenants
    with tenant_session(a.tenant_id, app_engine) as s:
        tenant_ids = set(s.scalars(select(model.tenant_id)))
    assert a.tenant_id in tenant_ids
    assert b.tenant_id not in tenant_ids


def _stamp(model):
    return getattr(model, "updated_at", None) or model.occurred_at


def _attempt(engine, tenant_id, stmt) -> int:
    """Run a write as the app role. Returns rows affected, or 0 if the role may not write the
    table at all (engine and audit tables are insert-only or status-only for the app)."""
    try:
        with tenant_session(tenant_id, engine) as s:
            return s.execute(stmt).rowcount
    except DBAPIError as exc:
        assert "permission denied" in str(exc), exc
        return 0


@pytest.mark.parametrize("model", TENANT_MODELS, ids=_by_name)
def test_cannot_update_other_tenant_rows(app_engine, tenants, model):
    a, b = tenants
    with tenant_session(b.tenant_id, app_engine) as s:
        before = sorted(s.scalars(select(_stamp(model))))
    stmt = update(model).where(model.tenant_id == b.tenant_id).values(tenant_id=model.tenant_id)
    assert _attempt(app_engine, a.tenant_id, stmt) == 0
    with tenant_session(b.tenant_id, app_engine) as s:
        assert sorted(s.scalars(select(_stamp(model)))) == before


@pytest.mark.parametrize("model", TENANT_MODELS, ids=_by_name)
def test_cannot_delete_other_tenant_rows(app_engine, tenants, model):
    a, b = tenants
    with tenant_session(b.tenant_id, app_engine) as s:
        before = s.scalar(select(func.count()).select_from(model))
    stmt = model.__table__.delete().where(model.tenant_id == b.tenant_id)
    _attempt(app_engine, a.tenant_id, stmt)
    with tenant_session(b.tenant_id, app_engine) as s:
        assert s.scalar(select(func.count()).select_from(model)) == before >= 1


@pytest.mark.parametrize("model", TENANT_MODELS, ids=_by_name)
def test_no_tenant_set_sees_nothing(app_engine, tenants, model):
    with app_engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(model)).scalar() == 0


def test_cannot_insert_row_for_other_tenant(app_engine, tenants):
    a, b = tenants
    with (
        pytest.raises(DBAPIError, match="row-level security"),
        tenant_session(a.tenant_id, app_engine) as s,
    ):
        s.add(Brand(tenant_id=b.tenant_id, slug="forged", name="Forged"))
        s.flush()


def test_cannot_insert_without_tenant(app_engine, tenants):
    a, _ = tenants
    with pytest.raises(DBAPIError, match="row-level security"), app_engine.begin() as conn:
        conn.execute(
            Brand.__table__.insert().values(
                id=uuid.uuid4(), tenant_id=a.tenant_id, slug="no-tenant", name="X"
            )
        )


@pytest.mark.parametrize(
    "build",
    [
        lambda a, b: LocationBrand(
            tenant_id=a.tenant_id, location_id=a.location_id, brand_id=b.brand_id
        ),
        lambda a, b: MembershipBrand(
            tenant_id=a.tenant_id, membership_id=a.membership_id, brand_id=b.brand_id
        ),
        lambda a, b: MembershipLocation(
            tenant_id=a.tenant_id, membership_id=a.membership_id, location_id=b.location_id
        ),
    ],
    ids=["location_brand", "membership_brand", "membership_location"],
)
def test_cannot_link_to_other_tenant_record(app_engine, tenants, build):
    a, b = tenants
    with pytest.raises(IntegrityError), tenant_session(a.tenant_id, app_engine) as s:
        s.add(build(a, b))
        s.flush()


def test_updated_at_maintained_for_raw_sql(app_engine, tenants):
    a, _ = tenants
    with tenant_session(a.tenant_id, app_engine) as s:
        before = s.scalar(select(Brand.updated_at).where(Brand.id == a.brand_id))
    with tenant_session(a.tenant_id, app_engine) as s:
        s.execute(text("UPDATE brands SET name = 'Renamed' WHERE id = :id"), {"id": a.brand_id})
        after = s.scalar(select(Brand.updated_at).where(Brand.id == a.brand_id))
    assert after > before


def test_tenant_setting_does_not_outlive_transaction(app_engine, tenants):
    a, _ = tenants
    with tenant_session(a.tenant_id, app_engine):
        pass
    with app_engine.connect() as conn:
        value = conn.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar()
    assert not value


LG_TABLES = ("checkpoint_blobs", "checkpoint_migrations", "checkpoint_writes", "checkpoints")


def test_app_role_cannot_bypass_rls(app_engine):
    with open_checkpointer(app_engine):  # make sure the library's tables exist
        pass
    with app_engine.connect() as conn:
        superuser, bypass = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        owned = conn.execute(
            text("SELECT schemaname || '.' || tablename FROM pg_tables "
                 "WHERE tableowner = current_user")
        ).scalars().all()  # fmt: skip
    assert (superuser, bypass) == (False, False)
    # The only tables the app role may own are the checkpointer's, in schema lg
    # (DECISIONS.md, E4.1): exactly these, nothing else.
    assert sorted(owned) == sorted(f"lg.{t}" for t in LG_TABLES)


def test_every_table_with_tenant_id_has_forced_rls_policy(app_engine):
    """Discovered from the catalog, so a new table without RLS fails here automatically."""
    with app_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       EXISTS (SELECT 1 FROM pg_policies p
                               WHERE p.schemaname = 'public' AND p.tablename = c.relname
                                 AND p.policyname = 'tenant_isolation'
                                 AND p.qual LIKE '%app.tenant_id%'
                                 AND p.with_check LIKE '%app.tenant_id%')
                FROM information_schema.columns col
                JOIN pg_class c ON c.relname = col.table_name
                JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = col.table_schema
                WHERE col.table_schema = 'public' AND col.column_name = 'tenant_id'
                  AND c.relkind = 'r'
                """
            )
        ).all()
    unsafe = [r.relname for r in rows if not (r[1] and r[2] and r[3])]
    assert rows, "no tenant tables found"
    assert unsafe == []


def test_every_table_with_updated_at_has_trigger(app_engine):
    with app_engine.connect() as conn:
        missing = (
            conn.execute(
                text(
                    """
                SELECT col.table_name
                FROM information_schema.columns col
                JOIN information_schema.tables t
                  ON t.table_schema = col.table_schema AND t.table_name = col.table_name
                WHERE col.table_schema = 'public' AND col.column_name = 'updated_at'
                  AND t.table_type = 'BASE TABLE'
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_trigger tg
                      JOIN pg_class c ON c.oid = tg.tgrelid
                      JOIN pg_proc p ON p.oid = tg.tgfoid
                      WHERE c.relname = col.table_name AND p.proname = 'set_updated_at'
                  )
                """
                )
            )
            .scalars()
            .all()
        )
    assert missing == []


def test_maintenance_role_cannot_bypass_rls(maint_engine):
    with maint_engine.connect() as conn:
        superuser, bypass = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert (superuser, bypass) == (False, False)


def test_unfiltered_maintenance_delete_stays_in_its_tenant(maint_engine, app_engine, tenants):
    """The point of the maintenance role: a forgotten WHERE tenant_id fails closed."""
    a, b = tenants
    with tenant_session(b.tenant_id, app_engine) as s:
        before = s.scalar(select(func.count()).select_from(Transaction))
    with tenant_session(uuid.uuid4(), maint_engine) as s:  # some other (empty) tenant
        assert s.execute(text("DELETE FROM transactions")).rowcount == 0
    with tenant_session(b.tenant_id, app_engine) as s:
        assert s.scalar(select(func.count()).select_from(Transaction)) == before >= 1
