"""S8.3: the rule behind a remedy amount is a structured basis built in code, rendered from
fixed templates in every language (hard rule 7). No model text can reach these lines."""

from types import SimpleNamespace

import pytest

from app.api.decision_sources import basis_lines
from app.core.i18n import LANGUAGES
from app.engine.resolver import _tier_basis, _voucher

SETTINGS = {
    "voucher_percent": 100,
    "voucher_auto_approve_max_paise": 30000,
    "voucher_max_paise": 50000,
}


def _codes(remedy):
    return [b["code"] for b in remedy.basis]


def test_voucher_below_every_cap_is_sized_to_the_order_total():
    r = _voucher("o", 24900, SETTINGS, "x")
    assert r.params["value_paise"] == 24900 - 24900 % 100
    assert _codes(r) == ["voucher_order_total"]


def test_voucher_above_a_cap_names_the_cap_that_bound_it():
    r = _voucher("o", 90000, SETTINGS, "x")
    assert r.params["value_paise"] == 30000
    assert r.basis[-1] == {"code": "voucher_cap", "params": {"cap_paise": 30000}}
    r = _voucher("o", 90000, {**SETTINGS, "voucher_auto_approve_max_paise": 80000}, "x")
    assert r.basis[-1]["params"]["cap_paise"] == 50000


def test_a_tier_leads_the_basis_of_its_voucher():
    tier = {"min_minutes_late": 30, "remedy": "voucher"}
    r = _voucher("o", 24900, SETTINGS, "x", (_tier_basis(tier, 41),))
    assert _codes(r) == ["late_tier", "voucher_order_total"]


@pytest.mark.parametrize("lang", LANGUAGES)
def test_every_basis_code_renders_in_every_language_from_templates(lang):
    items = [
        {"code": "voucher_order_total", "params": {"percent": 100}},
        {"code": "voucher_order_total", "params": {"percent": 50}},
        {"code": "voucher_cap", "params": {"cap_paise": 15000}},
        {"code": "late_tier", "params": {"tier_minutes": 30, "minutes": 41}},
        {"code": "refund_percent", "params": {"percent": 20, "capped": True}},
        {"code": "refund_choice", "params": {"percent": 20, "capped": False}},
        {"code": "refund_missing", "params": {"capped": True}},
        {"code": "approver_set", "params": {}},
    ]
    for item in items:
        lines = basis_lines(SimpleNamespace(validation={"basis": [item]}), lang)
        assert lines and all(line.strip() for line in lines), item
    cap = basis_lines(SimpleNamespace(validation={"basis": [items[2]]}), lang)[0]
    assert "150" in cap  # ASCII digits and the same figure in every language


def test_unknown_or_malformed_basis_is_skipped_never_shown():
    bad = [
        {"code": "made_up", "params": {}},
        {"code": "voucher_cap", "params": {}},  # missing cap
        {"code": "voucher_cap", "params": {"cap_paise": "<script>"}},
        "free text from a model",
        None,
    ]
    assert basis_lines(SimpleNamespace(validation={"basis": bad}), "en") == []
    assert basis_lines(SimpleNamespace(validation={}), "en") == []
    assert basis_lines(SimpleNamespace(validation=None), "en") == []


def test_cap_line_shows_the_amount_actually_given_after_rounding_down():
    # A cap that is not a whole number of rupees: the voucher is rounded down, and the line
    # must quote that figure, not the raw setting.
    settings = {**SETTINGS, "voucher_auto_approve_max_paise": 30050, "voucher_max_paise": 50000}
    r = _voucher("o", 90000, settings, "x")
    assert r.params["value_paise"] == 30000
    assert r.basis == ({"code": "voucher_cap", "params": {"cap_paise": 30000}},)
    line = basis_lines(SimpleNamespace(validation={"basis": list(r.basis)}), "en")[0]
    assert "300.00" in line and "300.50" not in line


def test_order_total_equal_to_the_cap_names_both_rules():
    r = _voucher("o", 30000, SETTINGS, "x")
    assert _codes(r) == ["voucher_order_total", "voucher_cap"]
    assert r.params["value_paise"] == 30000


def test_refund_choice_wording_is_neutral_for_staff_and_customer():
    from app.core.i18n import TEMPLATES

    for lang, text in TEMPLATES["basis.refund_choice"].items():
        assert "you" not in text.lower().split(), lang
        assert "aapne" not in text and "आपने" not in text, lang
