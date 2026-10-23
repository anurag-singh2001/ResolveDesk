import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError

from app.core.db import tenant_session
from app.core.models import TENANT_MODELS, Brand, Location, TenantSetting
from app.core.settings_resolver import effective_settings, resolve
from app.core.tenant_config import load_tenant
from app.core.tenant_loader import load_pack_into_db, load_tenant_into_db
from app.core.verticals import load_pack


@pytest.fixture
def loaded(app_engine, owner_engine, tenant):
    """(engine, cfg, pack, tenant_id) with the tenant folder loaded; reloaded clean afterwards."""
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    load_pack_into_db(owner_engine, pack)
    tid = load_tenant_into_db(app_engine, cfg, pack)
    yield app_engine, cfg, pack, tid
    load_tenant_into_db(app_engine, cfg, pack)


def _snapshot(engine, tenant_id):
    with tenant_session(tenant_id, engine) as s:
        return {
            m.__tablename__: (
                s.scalar(select(func.count()).select_from(m)),
                s.scalar(select(func.max(m.updated_at))),
            )
            for m in TENANT_MODELS
        }


def test_loader_is_idempotent(loaded):
    engine, cfg, pack, tid = loaded
    first = _snapshot(engine, tid)

    assert load_tenant_into_db(engine, cfg, pack) == tid
    assert _snapshot(engine, tid) == first  # same counts, no row rewritten
    assert first["organizations"][0] == 1
    assert first["locations"][0] == len(cfg.locations)
    assert first["catalogue_items"][0] == len(cfg.catalogue)


def test_removed_entries_are_deleted(loaded):
    engine, cfg, pack, tid = loaded
    scoped_user = next(u for u in cfg.users if u.locations)
    trimmed = cfg.model_copy(deep=True)
    next(u for u in trimmed.users if u.email == scoped_user.email).locations = []
    trimmed.catalogue = trimmed.catalogue[1:]

    load_tenant_into_db(engine, trimmed, pack)

    snap = _snapshot(engine, tid)
    expected_scopes = sum(len(u.locations) for u in trimmed.users)
    assert snap["membership_locations"][0] == expected_scopes
    assert snap["catalogue_items"][0] == len(cfg.catalogue) - 1


def test_db_settings_match_file_resolution(loaded):
    engine, cfg, pack, tid = loaded
    with tenant_session(tid, engine) as s:
        brand_ids = dict(s.execute(select(Brand.slug, Brand.id)).all())
        location_ids = dict(s.execute(select(Location.slug, Location.id)).all())
        for loc in cfg.locations:
            for brand in loc.brands:
                from_db = effective_settings(
                    s, brand_id=brand_ids[brand], location_id=location_ids[loc.slug]
                )
                from_file = resolve(
                    pack.settings,
                    cfg.settings.org,
                    cfg.settings.brands.get(brand, {}),
                    cfg.settings.locations.get(loc.slug, {}),
                )
                assert from_db == from_file


def test_db_row_cannot_loosen_a_limit(loaded):
    engine, cfg, pack, tid = loaded
    key = next(k for k, spec in pack.settings.items() if spec.kind == "limit")
    with tenant_session(tid, engine) as s:
        brand_id = s.scalars(select(Brand.id)).first()
        before = effective_settings(s, brand_id=brand_id)[key]
        s.execute(
            TenantSetting.__table__.delete().where(
                TenantSetting.brand_id == brand_id, TenantSetting.key == key
            )
        )
        s.add(TenantSetting(tenant_id=tid, brand_id=brand_id, key=key, value=before + 100000))
        s.flush()
        assert effective_settings(s, brand_id=brand_id)[key] == before
    # The fixture's reload prunes the inserted row and restores the deleted one.


def test_app_role_cannot_modify_vertical_packs(app_engine, loaded):
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("UPDATE vertical_packs SET version = version + 1"))
