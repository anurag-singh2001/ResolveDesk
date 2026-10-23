import re
from pathlib import Path

import pytest

from app.core.settings_resolver import resolve
from app.core.tenant_config import load_tenant, tenant_dirs, validate_tenant
from app.core.verticals import ROOT, load_pack


def test_tenant_folder_is_valid(tenant):
    cfg = load_tenant(tenant)
    validate_tenant(cfg, load_pack(cfg.vertical_pack))


def test_catalogue_prices_are_integer_paise(tenant):
    cfg = load_tenant(tenant)
    assert cfg.catalogue
    assert all(type(i.price_paise) is int and i.price_paise > 0 for i in cfg.catalogue)


def test_effective_limits_never_exceed_pack_defaults(tenant):
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    limits = {k: s.default for k, s in pack.settings.items() if s.kind == "limit"}
    for loc in cfg.locations:
        for brand in loc.brands:
            eff = resolve(
                pack.settings,
                cfg.settings.org,
                cfg.settings.brands.get(brand, {}),
                cfg.settings.locations.get(loc.slug, {}),
            )
            assert all(eff[k] <= default for k, default in limits.items())


def test_every_user_scope_is_known(tenant):
    cfg = load_tenant(tenant)
    locations = {loc.slug for loc in cfg.locations}
    for user in cfg.users:
        assert set(user.locations) <= locations


def test_float_price_rejected(tmp_path, tenant):
    folder = tmp_path / tenant.name
    folder.mkdir()
    (folder / "tenant.yaml").write_text((tenant / "tenant.yaml").read_text(encoding="utf-8"))
    lines = (tenant / "catalogue.csv").read_text(encoding="utf-8").splitlines()
    first = lines[1].rsplit(",", 1)[0] + ",349.50"
    (folder / "catalogue.csv").write_text("\n".join([lines[0], first]) + "\n")
    with pytest.raises(ValueError):
        load_tenant(folder)


def test_setting_on_brand_without_location_is_still_validated(tenant):
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    limit_key = next(k for k, spec in pack.settings.items() if spec.kind == "limit")
    cfg.brands.append(type(cfg.brands[0])(slug="unused_brand", name="Unused"))
    cfg.settings.brands["unused_brand"] = {limit_key: 10.5}
    with pytest.raises(ValueError):
        validate_tenant(cfg, pack)


def test_only_scripts_import_the_tenant_loader():
    """The loader sets the tenant from a folder (admin path); request code must not use it."""
    hits = [
        str(path.relative_to(ROOT))
        for path in Path(ROOT, "app").rglob("*.py")
        if path.name != "tenant_loader.py" and "tenant_loader" in path.read_text(encoding="utf-8")
    ]
    assert hits == []


def _tenant_identifiers() -> set[str]:
    names: set[str] = set()
    for folder in tenant_dirs():
        cfg = load_tenant(folder)
        names |= {cfg.slug, cfg.name}
        names |= {b.slug for b in cfg.brands} | {loc.slug for loc in cfg.locations}
    return names


@pytest.mark.parametrize("code_dir", ["app", "scripts", "migrations"])
def test_core_code_never_names_a_tenant(code_dir):
    """Hard rule 2: tenant differences live in config, never in core code."""
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(n) for n in _tenant_identifiers()) + r")\b", re.IGNORECASE
    )
    hits = [
        f"{path.relative_to(ROOT)}:{n}"
        for path in Path(ROOT, code_dir).rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []
