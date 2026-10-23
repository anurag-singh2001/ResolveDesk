import hashlib

from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.models import COMMERCE_MODELS
from app.core.tenancy import tenant_id_for
from app.core.verticals import load_pack
from simulator.load import load_history
from tests.helpers import HISTORY_SCALE


def _db_fingerprint(engine, slug) -> dict[str, tuple[int, str]]:
    """Per table: row count and a hash of the sorted ids (ids are deterministic)."""
    out = {}
    with tenant_session(tenant_id_for(slug), engine) as s:
        for m in COMMERCE_MODELS:
            ids = sorted(str(i) for i in s.scalars(select(m.id)))
            out[m.__tablename__] = (len(ids), hashlib.sha256(",".join(ids).encode()).hexdigest())
    return out


def test_reload_with_same_seed_is_identical(app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    first = _db_fingerprint(app_engine, cfg.slug)
    history = load_history(app_engine, cfg, load_pack(cfg.vertical_pack), scale=HISTORY_SCALE)
    assert _db_fingerprint(app_engine, cfg.slug) == first
    assert first["transactions"][0] == len(history.transactions) > 0


def test_every_money_column_is_bigint(app_engine):
    query = (
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name LIKE '%\\_paise'"
    )
    with app_engine.connect() as conn:
        columns = conn.execute(text(query)).all()
    assert columns, "no *_paise columns found"
    assert [c for c in columns if c.data_type != "bigint"] == []
