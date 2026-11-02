"""Pack schema for remedy options (S7.9): old single rules stay valid; bad options are refused."""

import pytest
from pydantic import ValidationError

from app.core.tenant_config import load_tenant
from app.core.verticals import RemedyOptions, VerticalPack, load_pack, option_code, rule_options


def _pack(tenant, remedies):
    base = load_pack(load_tenant(tenant).vertical_pack).model_dump()
    cat = base["issue_categories"][0]
    return VerticalPack.model_validate({**base, "remedies": {cat: remedies}}), cat


def test_a_plain_rule_name_is_one_option(tenant):
    pack, cat = _pack(tenant, "voucher")
    assert rule_options(pack.remedies[cat]) == ["voucher"]


def test_options_list_parses_to_codes(tenant):
    pack, cat = _pack(tenant, {"options": ["voucher", {"refund_percent": 50}]})
    rule = pack.remedies[cat]
    assert isinstance(rule, RemedyOptions)
    assert [option_code(o) for o in rule.options] == ["voucher", "refund_50pct"]


@pytest.mark.parametrize(
    "bad",
    [
        {"options": []},
        {"options": ["voucher", "voucher"]},
        {"options": [{"refund_percent": 0}]},
        {"options": [{"refund_percent": 101}]},
        {"options": [{"refund_percent": 12.5}]},
        {"options": ["cash"]},
        {"options": ["voucher"], "extra": 1},
    ],
)
def test_bad_options_are_refused(tenant, bad):
    with pytest.raises(ValidationError):
        _pack(tenant, bad)


def test_baseline_probe_applies_the_pick_only_to_the_cases_own_category():
    from types import SimpleNamespace

    from app.engine.baseline import remedy_probe

    case = SimpleNamespace(category="a", transaction_id="t", remedy_choice="refund_50pct")
    assert remedy_probe(case, "a").remedy_choice == "refund_50pct"
    assert remedy_probe(case, "b").remedy_choice is None
