"""Tenant folder format (tenants/<slug>/tenant.yaml + catalogue.csv) and its validation.

Generic: nothing here may mention a specific tenant.
"""

import csv
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, StrictInt

from app.core.settings_resolver import SettingsError, resolve, validate_setting
from app.core.verticals import ROOT, VerticalPack

TENANTS_DIR = ROOT / "tenants"

Role = Literal["customer", "location_manager", "franchisee_owner", "hq_owner"]


class BrandCfg(BaseModel):
    slug: str
    name: str


class LocationCfg(BaseModel):
    slug: str
    name: str
    brands: list[str]


class UserCfg(BaseModel):
    email: str
    name: str
    role: Role
    brands: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)


class SettingsCfg(BaseModel):
    org: dict[str, Any] = Field(default_factory=dict)
    brands: dict[str, dict[str, Any]] = Field(default_factory=dict)
    locations: dict[str, dict[str, Any]] = Field(default_factory=dict)


class CatalogueItemCfg(BaseModel):
    brand: str
    sku: str
    name: str
    category: str
    price_paise: StrictInt = Field(ge=0)


class TenantConfig(BaseModel):
    slug: str
    name: str
    vertical_pack: str
    brands: list[BrandCfg]
    locations: list[LocationCfg]
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    settings: SettingsCfg = Field(default_factory=SettingsCfg)
    users: list[UserCfg] = Field(default_factory=list)
    catalogue: list[CatalogueItemCfg] = Field(default_factory=list)


def tenant_dirs(root: Path = TENANTS_DIR) -> list[Path]:
    return sorted(p for p in root.iterdir() if (p / "tenant.yaml").is_file())


def load_tenant(folder: Path) -> TenantConfig:
    data = yaml.safe_load((folder / "tenant.yaml").read_text(encoding="utf-8"))
    catalogue_path = folder / "catalogue.csv"
    if catalogue_path.is_file():
        with catalogue_path.open(encoding="utf-8", newline="") as f:
            # int() rejects "349.50": catalogue prices must already be integer paise.
            data["catalogue"] = [
                {**row, "price_paise": int(row["price_paise"])} for row in csv.DictReader(f)
            ]
    cfg = TenantConfig.model_validate(data)
    if cfg.slug != folder.name:
        raise ValueError(f"{folder.name}/tenant.yaml declares slug {cfg.slug!r}")
    return cfg


def validate_tenant(cfg: TenantConfig, pack: VerticalPack) -> None:
    """Cross-reference checks the schema alone can't express. Raises ValueError."""
    if cfg.vertical_pack != pack.slug:
        raise ValueError(f"tenant uses pack {cfg.vertical_pack!r}, got {pack.slug!r}")
    brands = _unique([b.slug for b in cfg.brands], "brand")
    locations = _unique([loc.slug for loc in cfg.locations], "location")
    _unique([u.email for u in cfg.users], "user email")
    _unique([i.sku for i in cfg.catalogue], "sku")

    for loc in cfg.locations:
        _known(loc.brands, brands, f"location {loc.slug} brand")
    for user in cfg.users:
        _known(user.brands, brands, f"user {user.email} brand")
        _known(user.locations, locations, f"user {user.email} location")
    _known([i.brand for i in cfg.catalogue], brands, "catalogue brand")
    _known(cfg.settings.brands, brands, "settings brand")
    _known(cfg.settings.locations, locations, "settings location")
    _known(cfg.feature_flags, set(pack.features), "feature flag")

    try:
        # Every override on its own (also brands no location carries), then every combination.
        for layer in [
            cfg.settings.org,
            *cfg.settings.brands.values(),
            *cfg.settings.locations.values(),
        ]:
            for key, value in layer.items():
                validate_setting(pack.settings, key, value)
        for loc in cfg.locations:
            for brand in loc.brands:
                resolve(
                    pack.settings,
                    cfg.settings.org,
                    cfg.settings.brands.get(brand, {}),
                    cfg.settings.locations.get(loc.slug, {}),
                )
    except SettingsError as exc:
        raise ValueError(f"settings: {exc}") from exc


def _unique(values: list[str], what: str) -> set[str]:
    seen = set(values)
    if len(seen) != len(values):
        raise ValueError(f"duplicate {what}")
    return seen


def _known(values, known: set[str], what: str) -> None:
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"unknown {what}: {sorted(unknown)}")
