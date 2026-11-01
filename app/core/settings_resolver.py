"""Effective settings: vertical pack default -> org -> brand -> location.

Limits can only tighten: effective = min(parent, override). Values are replaced.
"""

import copy
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Organization, TenantSetting, VerticalPackRow
from app.core.verticals import SettingSpec, VerticalPack, is_limit_value


class SettingsError(ValueError):
    pass


def validate_setting(specs: Mapping[str, SettingSpec], key: str, value: Any) -> None:
    spec = specs.get(key)
    if spec is None:
        raise SettingsError(f"unknown setting {key!r}")
    if spec.kind == "limit" and not is_limit_value(value):
        raise SettingsError(f"{key} must be a non-negative integer, got {value!r}")
    if spec.allowed is not None and value not in spec.allowed:
        raise SettingsError(f"{key} must be one of {spec.allowed}, got {value!r}")


def resolve(specs: Mapping[str, SettingSpec], *layers: Mapping[str, Any]) -> dict[str, Any]:
    """Apply override layers from broadest to narrowest (org, brand, location)."""
    effective = {key: copy.deepcopy(spec.default) for key, spec in specs.items()}
    for layer in layers:
        for key, value in layer.items():
            validate_setting(specs, key, value)
            if specs[key].kind == "limit":
                effective[key] = min(effective[key], value)
            else:
                effective[key] = copy.deepcopy(value)
    return effective


def tenant_pack_row(session: Session) -> VerticalPackRow:
    """The pack row of the tenant set on this session, in ONE round trip (RLS shows exactly one
    organization). Two separate selects cost two trips to the remote database."""
    return session.scalars(
        select(VerticalPackRow).join(
            Organization, Organization.vertical_pack == VerticalPackRow.slug
        )
    ).one()


def tenant_pack(session: Session) -> VerticalPack:
    """The pack of the tenant set on this session."""
    return VerticalPack.model_validate(tenant_pack_row(session).definition)


def effective_settings(
    session: Session,
    brand_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    *,
    pack: VerticalPack | None = None,
    rows: list[TenantSetting] | None = None,
) -> dict[str, Any]:
    """Settings for the session's tenant, optionally narrowed to a brand and/or location.
    A caller that already loaded the pack or the setting rows may pass them to save a query;
    they must come from this same session and transaction (RLS scopes them to one tenant)."""
    pack = pack or tenant_pack(session)
    if rows is None:
        rows = list(session.scalars(select(TenantSetting)))
    org: dict[str, Any] = {}
    brand: dict[str, Any] = {}
    location: dict[str, Any] = {}
    for row in rows:
        if row.brand_id is None and row.location_id is None:
            org[row.key] = row.value
        elif row.brand_id is not None and row.brand_id == brand_id:
            brand[row.key] = row.value
        elif row.location_id is not None and row.location_id == location_id:
            location[row.key] = row.value
    return resolve(pack.settings, org, brand, location)
