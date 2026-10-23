"""Persist generated history for one tenant: replace its commerce rows in one transaction."""

from sqlalchemy import Engine, delete, insert, select

from app.config import get_settings
from app.core.db import tenant_session
from app.core.models import COMMERCE_MODELS, ENGINE_MODELS, Brand, Location, User
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import TenantConfig
from app.core.verticals import VerticalPack
from simulator.generate import History, Refs, generate

BATCH = 1000


def load_refs(session, tenant_id) -> Refs:
    """Ids by slug/email for ONE tenant. Filtered explicitly: callers may hold a session that
    RLS doesn't constrain (the owner on Neon), and slugs repeat across tenants."""

    def by(key, model):
        rows = session.execute(select(key, model.id).where(model.tenant_id == tenant_id))
        return {k: v for k, v in rows}

    return Refs(
        tenant_id=tenant_id,
        brand_ids=by(Brand.slug, Brand),
        location_ids=by(Location.slug, Location),
        user_ids=by(User.email, User),
    )


def load_history(
    engine: Engine, cfg: TenantConfig, pack: VerticalPack, seed: int = 42, scale: float = 1.0
) -> History:
    """Regenerate and replace this tenant's history. The tenant config must already be loaded.

    `engine` must be the OWNER engine: the app role may not delete engine rows (cases,
    proposals, approvals...), by design. On Neon the owner has BYPASSRLS, so RLS does NOT
    limit it: every statement here filters on tenant_id explicitly.

    Admin/seed path (like the tenant loader): the tenant comes from the folder, not a request.
    """
    if get_settings().app_env == "prod":
        # Reseeding replaces every commerce row: never against production data.
        raise RuntimeError("refusing to (re)generate history when APP_ENV=prod")
    tenant_id = tenant_id_for(cfg.slug)
    # tenant_session still sets app.tenant_id, but for the owner that protects nothing: the
    # tenant filters below do.
    with tenant_session(tenant_id, engine) as session:
        history = generate(cfg, pack, load_refs(session, tenant_id), seed=seed, scale=scale)
        # Engine rows (cases, proposals, refunds) reference commerce rows: clear them first,
        # children first. Audit events are append-only and stay.
        for model in [*reversed(ENGINE_MODELS), *reversed(COMMERCE_MODELS)]:
            session.execute(delete(model).where(model.tenant_id == tenant_id))
        for model, rows in history.tables():
            for i in range(0, len(rows), BATCH):
                session.execute(insert(model), rows[i : i + BATCH])
    return history
