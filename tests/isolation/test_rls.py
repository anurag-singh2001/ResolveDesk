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
)

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


@pytest.mark.parametrize("model", TENANT_MODELS, ids=_by_name)
def test_cannot_update_other_tenant_rows(app_engine, tenants, model):
    a, b = tenants
    with tenant_session(b.tenant_id, app_engine) as s:
        before = sorted(s.scalars(select(model.updated_at)))
    with tenant_session(a.tenant_id, app_engine) as s:
        result = s.execute(
            update(model).where(model.tenant_id == b.tenant_id).values(updated_at=func.now())
        )
    assert result.rowcount == 0
    with tenant_session(b.tenant_id, app_engine) as s:
        assert sorted(s.scalars(select(model.updated_at))) == before


@pytest.mark.parametrize("model", TENANT_MODELS, ids=_by_name)
def test_cannot_delete_other_tenant_rows(app_engine, tenants, model):
    a, b = tenants
    with tenant_session(b.tenant_id, app_engine) as s:
        before = s.scalar(select(func.count()).select_from(model))
    with tenant_session(a.tenant_id, app_engine) as s:
        s.execute(model.__table__.delete().where(model.tenant_id == b.tenant_id))
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


def test_app_role_cannot_bypass_rls(app_engine):
    with app_engine.connect() as conn:
        superuser, bypass = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        owned = conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE tableowner = current_user")
        ).scalar()
    assert (superuser, bypass, owned) == (False, False, 0)


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
