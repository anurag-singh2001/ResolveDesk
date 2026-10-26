"""make refresh: re-applying tenant packs is idempotent and never touches order history.

Runs for every tenant folder and never names one.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

import scripts.refresh as refresh_script
from app.core.db import tenant_session
from app.core.models import COMMERCE_MODELS, FeatureFlag, TenantSetting
from app.core.tenancy import tenant_id_for
from app.rag.embeddings import HashEmbedder
from scripts.seed import refresh_packs


def _state(engine, slug):
    """Every setting and flag row, plus the row count of each order-history table."""
    with tenant_session(tenant_id_for(slug), engine) as s:
        settings = sorted(
            (str(r.brand_id), str(r.location_id), r.key, repr(r.value))
            for r in s.scalars(select(TenantSetting))
        )
        flags = sorted((r.key, r.enabled) for r in s.scalars(select(FeatureFlag)))
        history = {
            m.__tablename__: s.scalar(select(func.count()).select_from(m)) for m in COMMERCE_MODELS
        }
    return settings, flags, history


def test_refreshing_twice_changes_neither_settings_nor_history(
    app_engine, owner_engine, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    before = _state(app_engine, cfg.slug)
    assert before[0] and before[2]["transactions"] > 0  # something to compare
    for _ in range(2):
        refresh_packs([tenant], owner_engine, app_engine, HashEmbedder())
        assert _state(app_engine, cfg.slug) == before


@pytest.mark.parametrize("env", ["prod", "test"])
def test_refresh_does_nothing_outside_dev(monkeypatch, env):
    def boom(*a, **k):
        raise AssertionError("refresh must not run outside dev")

    monkeypatch.setattr(refresh_script, "get_settings", lambda: SimpleNamespace(app_env=env))
    monkeypatch.setattr(refresh_script, "refresh_packs", boom)
    assert refresh_script.main() == 0
