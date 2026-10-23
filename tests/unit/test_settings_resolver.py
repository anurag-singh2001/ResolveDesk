import pytest

from app.core.settings_resolver import SettingsError, resolve
from app.core.verticals import SettingSpec

SPECS = {
    "cap_paise": SettingSpec(kind="limit", default=50000),
    "channel": SettingSpec(kind="value", default="a", allowed=["a", "b"]),
    "tiers": SettingSpec(kind="value", default=[{"min": 0}]),
}


def test_defaults_when_no_overrides():
    assert resolve(SPECS) == {"cap_paise": 50000, "channel": "a", "tiers": [{"min": 0}]}


def test_layers_apply_org_then_brand_then_location():
    eff = resolve(SPECS, {"cap_paise": 40000}, {"cap_paise": 30000}, {"cap_paise": 20000})
    assert eff["cap_paise"] == 20000


@pytest.mark.parametrize(
    "layers",
    [
        ({"cap_paise": 90000},),  # org tries to exceed the pack
        ({"cap_paise": 30000}, {"cap_paise": 40000}),  # brand tries to loosen org
        ({"cap_paise": 30000}, {}, {"cap_paise": 45000}),  # location tries to loosen org
    ],
)
def test_limit_override_can_only_tighten(layers):
    expected = min([50000] + [layer["cap_paise"] for layer in layers if layer])
    assert resolve(SPECS, *layers)["cap_paise"] == expected


def test_value_override_replaces():
    assert resolve(SPECS, {"channel": "a"}, {"channel": "b"})["channel"] == "b"


def test_defaults_are_not_shared_between_calls():
    resolve(SPECS)["tiers"].append({"min": 99})
    assert resolve(SPECS)["tiers"] == [{"min": 0}]


@pytest.mark.parametrize(
    "layer",
    [
        {"unknown": 1},
        {"cap_paise": 100.5},  # float money
        {"cap_paise": "100"},
        {"cap_paise": True},
        {"cap_paise": -1},
        {"channel": "c"},  # not in allowed
    ],
)
def test_invalid_overrides_rejected(layer):
    with pytest.raises(SettingsError):
        resolve(SPECS, layer)


def test_limit_spec_requires_integer_default():
    with pytest.raises(ValueError):
        SettingSpec(kind="limit", default=10.0)
