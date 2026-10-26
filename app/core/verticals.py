"""Vertical packs: per-business-type defaults (categories, actions, settings schema)."""

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, model_validator

ROOT = Path(__file__).resolve().parents[2]
VERTICALS_DIR = ROOT / "verticals"
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SettingSpec(BaseModel):
    """kind=limit: integer ceiling, lower levels may only lower it. kind=value: replaced."""

    kind: Literal["limit", "value"]
    default: Any
    allowed: list[Any] | None = None

    @model_validator(mode="after")
    def _check_default(self) -> "SettingSpec":
        if self.kind == "limit" and not is_limit_value(self.default):
            raise ValueError("limit default must be a non-negative integer")
        if self.allowed is not None and self.default not in self.allowed:
            raise ValueError("default must be one of allowed")
        return self


class VerticalPack(BaseModel):
    slug: str
    name: str
    version: int
    vocabulary: dict[str, str]
    order_sources: list[str]
    fulfilment_kinds: dict[str, str] = {}  # order source -> delivery | pickup | counter
    issue_categories: list[str]
    actions: list[str]
    # issue category -> deterministic remedy rule (app/engine/resolver.py); others escalate
    remedies: dict[str, Literal["late_tiers", "refund_missing", "voucher"]] = {}
    metrics: list[str]
    features: dict[str, bool]
    settings: dict[str, SettingSpec]

    @model_validator(mode="after")
    def _remedies_use_known_categories(self) -> "VerticalPack":
        unknown = set(self.remedies) - set(self.issue_categories)
        if unknown:
            raise ValueError(f"remedies for unknown issue categories: {sorted(unknown)}")
        return self


def is_limit_value(value: Any) -> bool:
    # bool is an int subclass; floats are never allowed (money is integer paise).
    return type(value) is int and value >= 0


def load_pack(slug: str, root: Path = VERTICALS_DIR) -> VerticalPack:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid vertical pack slug: {slug!r}")
    data = yaml.safe_load((root / f"{slug}.yaml").read_text(encoding="utf-8"))
    pack = VerticalPack.model_validate(data)
    if pack.slug != slug:
        raise ValueError(f"pack file {slug}.yaml declares slug {pack.slug!r}")
    return pack
