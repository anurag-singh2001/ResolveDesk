"""Load a tenant folder into the database. Idempotent: a second run changes nothing.

IDs are deterministic (uuid5 of slugs), so reruns upsert the same rows, and rows are only
rewritten when a value actually changed. Admin/seed path: the tenant comes from the folder
being loaded, never from a request.
"""

import uuid
from typing import Any

from sqlalchemy import Engine, delete, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import tenant_session
from app.core.models import (
    CONFIG_MODELS,
    Brand,
    CatalogueItem,
    FeatureFlag,
    Location,
    LocationBrand,
    Membership,
    MembershipBrand,
    MembershipLocation,
    Organization,
    TenantSetting,
    User,
    VerticalPackRow,
)
from app.core.tenancy import NAMESPACE, tenant_id_for
from app.core.tenant_config import TenantConfig, validate_tenant
from app.core.verticals import VerticalPack


def _id(tenant_id: uuid.UUID, kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(tenant_id, f"{kind}:{key}")


def _upsert(session: Session, model, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    stmt = insert(model).values(rows)
    columns = [c for c in rows[0] if c not in ("id", "tenant_id")]
    if not columns:
        session.execute(stmt.on_conflict_do_nothing(index_elements=["id"]))
        return
    table = model.__table__
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={c: stmt.excluded[c] for c in columns},
            where=or_(*(table.c[c].is_distinct_from(stmt.excluded[c]) for c in columns)),
        )
    )


def load_pack_into_db(owner_engine: Engine, pack: VerticalPack) -> None:
    """Packs are platform-wide; the app role can only read them, so write as the owner."""
    with Session(owner_engine) as session, session.begin():
        _upsert(
            session,
            VerticalPackRow,
            [
                {
                    "id": uuid.uuid5(NAMESPACE, f"pack:{pack.slug}"),
                    "slug": pack.slug,
                    "version": pack.version,
                    "definition": pack.model_dump(mode="json"),
                }
            ],
        )


def load_tenant_into_db(engine: Engine, cfg: TenantConfig, pack: VerticalPack) -> uuid.UUID:
    """Sync the tenant's rows to the folder: upsert what's there, delete what isn't.

    The pack must already be stored (load_pack_into_db with the owner engine).
    """
    validate_tenant(cfg, pack)
    tid = tenant_id_for(cfg.slug)
    brand_ids = {b.slug: _id(tid, "brand", b.slug) for b in cfg.brands}
    location_ids = {loc.slug: _id(tid, "location", loc.slug) for loc in cfg.locations}
    loaded: dict[type, set[uuid.UUID]] = {}

    # Positional-only: some tables have a column called "key".
    def row(kind: str, natural_key: str, /, **values: Any) -> dict[str, Any]:
        return {"id": _id(tid, kind, natural_key), "tenant_id": tid, **values}

    def put(model, rows: list[dict[str, Any]]) -> None:
        _upsert(s, model, rows)
        loaded[model] = {r["id"] for r in rows}

    with tenant_session(tid, engine) as s:
        put(
            Organization,
            [
                {
                    "id": tid,
                    "tenant_id": tid,
                    "slug": cfg.slug,
                    "name": cfg.name,
                    "vertical_pack": cfg.vertical_pack,
                }
            ],
        )
        put(Brand, [row("brand", b.slug, slug=b.slug, name=b.name) for b in cfg.brands])
        put(
            Location,
            [row("location", loc.slug, slug=loc.slug, name=loc.name) for loc in cfg.locations],
        )
        put(
            LocationBrand,
            [
                row(
                    "location_brand",
                    f"{loc.slug}:{b}",
                    location_id=location_ids[loc.slug],
                    brand_id=brand_ids[b],
                )
                for loc in cfg.locations
                for b in loc.brands
            ],
        )
        put(
            User,
            [row("user", u.email, email=u.email, display_name=u.name) for u in cfg.users],
        )
        put(
            Membership,
            [
                row("membership", u.email, user_id=_id(tid, "user", u.email), role=u.role)
                for u in cfg.users
            ],
        )
        put(
            MembershipBrand,
            [
                row(
                    "membership_brand",
                    f"{u.email}:{b}",
                    membership_id=_id(tid, "membership", u.email),
                    brand_id=brand_ids[b],
                )
                for u in cfg.users
                for b in u.brands
            ],
        )
        put(
            MembershipLocation,
            [
                row(
                    "membership_location",
                    f"{u.email}:{loc}",
                    membership_id=_id(tid, "membership", u.email),
                    location_id=location_ids[loc],
                )
                for u in cfg.users
                for loc in u.locations
            ],
        )
        settings = [
            row("setting", f"org::{k}", brand_id=None, location_id=None, key=k, value=v)
            for k, v in cfg.settings.org.items()
        ]
        settings += [
            row(
                "setting", f"brand:{b}:{k}", brand_id=brand_ids[b], location_id=None, key=k, value=v
            )
            for b, layer in cfg.settings.brands.items()
            for k, v in layer.items()
        ]
        settings += [
            row(
                "setting",
                f"location:{loc}:{k}",
                brand_id=None,
                location_id=location_ids[loc],
                key=k,
                value=v,
            )
            for loc, layer in cfg.settings.locations.items()
            for k, v in layer.items()
        ]
        put(TenantSetting, settings)
        put(
            FeatureFlag,
            [row("flag", k, key=k, enabled=v) for k, v in cfg.feature_flags.items()],
        )
        put(
            CatalogueItem,
            [
                row(
                    "sku",
                    i.sku,
                    brand_id=brand_ids[i.brand],
                    sku=i.sku,
                    name=i.name,
                    category=i.category,
                    price_paise=i.price_paise,
                )
                for i in cfg.catalogue
            ],
        )
        # Removed from the folder => removed from the DB, so a dropped scope can't stay live.
        # Children first; RLS limits the delete to this tenant.
        for model in reversed(CONFIG_MODELS):
            if model is Organization:
                continue
            try:
                s.execute(delete(model).where(model.id.not_in(loaded.get(model, set()))))
            except IntegrityError as exc:  # whole load rolls back; nothing half-applied
                raise TenantLoadError(
                    f"{cfg.slug}: can't remove {model.__tablename__} rows that orders or other "
                    "history still reference. Keep them in the folder, or reseed history first."
                ) from exc
    return tid


class TenantLoadError(ValueError):
    pass
