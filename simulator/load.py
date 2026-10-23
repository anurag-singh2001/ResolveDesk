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
    """Ids by slug/email for ONE tenant. Filtered explicitly as well as by RLS: slugs repeat
    across tenants, and a session that RLS doesn't constrain must still get the right ids."""

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

    `engine` must be the MAINTENANCE engine (resolvedesk_maint): the app role may not delete
    engine rows (cases, proposals, approvals...), by design, and the owner bypasses RLS on
    Neon. The maintenance role is NOBYPASSRLS, so RLS limits every statement to this tenant;
    the explicit tenant_id filters below are a second layer.

    Admin/seed path (like the tenant loader): the tenant comes from the folder, not a request.
    """
    if get_settings().app_env == "prod":
        # Reseeding replaces every commerce row: never against production data.
        raise RuntimeError("refusing to (re)generate history when APP_ENV=prod")
    tenant_id = tenant_id_for(cfg.slug)
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
