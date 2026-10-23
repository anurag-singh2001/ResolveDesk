"""Persist generated history for one tenant: replace its commerce rows in one transaction."""

from sqlalchemy import Engine, delete, insert, select

from app.core.db import tenant_session
from app.core.models import COMMERCE_MODELS, Brand, Location, User
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import TenantConfig
from app.core.verticals import VerticalPack
from simulator.generate import History, Refs, generate

BATCH = 1000


def load_refs(session, tenant_id) -> Refs:
    return Refs(
        tenant_id=tenant_id,
        brand_ids=dict(session.execute(select(Brand.slug, Brand.id)).all()),
        location_ids=dict(session.execute(select(Location.slug, Location.id)).all()),
        user_ids=dict(session.execute(select(User.email, User.id)).all()),
    )


def load_history(
    engine: Engine, cfg: TenantConfig, pack: VerticalPack, seed: int = 42, scale: float = 1.0
) -> History:
    """Regenerate and replace this tenant's history. The tenant config must already be loaded.

    Admin/seed path (like the tenant loader): the tenant comes from the folder, not a request.
    """
    tenant_id = tenant_id_for(cfg.slug)
    with tenant_session(tenant_id, engine) as session:
        history = generate(cfg, pack, load_refs(session, tenant_id), seed=seed, scale=scale)
        for model in reversed(COMMERCE_MODELS):  # children first; RLS keeps it to this tenant
            session.execute(delete(model))
        for model, rows in history.tables():
            for i in range(0, len(rows), BATCH):
                session.execute(insert(model), rows[i : i + BATCH])
    return history
