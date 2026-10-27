"""S7.8: a voucher never exceeds what the customer paid, and scales with the order."""

import uuid

from app.actions.base import Facts, get_action
from app.core.settings_resolver import resolve
from app.core.tenant_config import load_tenant
from app.core.verticals import load_pack
from app.engine.resolver import _voucher

WIDE = {"voucher_percent": 100, "voucher_auto_approve_max_paise": 15000, "voucher_max_paise": 30000}


def _settings(tenant):
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    return pack, resolve(pack.settings, cfg.settings.org)


def test_voucher_percent_is_a_lowerable_pack_default(tenant):
    pack, s = _settings(tenant)
    spec = pack.settings["voucher_percent"]
    assert spec.kind == "limit" and spec.default == 100
    assert s["voucher_percent"] <= 100


def test_149_rupee_order_never_gets_more_than_149(tenant):
    _, s = _settings(tenant)
    r = _voucher("o", 14900, {**s, **WIDE}, "x")
    assert r.action == "free_item_voucher"
    assert r.params["value_paise"] == 14900  # 100% of the order, whole rupees, under the caps


def test_odd_paise_round_down_to_whole_rupees(tenant):
    _, s = _settings(tenant)
    assert _voucher("o", 14950, {**s, **WIDE}, "x").params["value_paise"] == 14900


def test_large_order_is_capped_at_the_auto_approve_cap(tenant):
    _, s = _settings(tenant)
    r = _voucher("o", 100000, {**s, "voucher_percent": 100}, "x")
    assert r.params["value_paise"] == min(
        s["voucher_auto_approve_max_paise"], s["voucher_max_paise"]
    )


def test_lower_percent_scales_with_the_order(tenant):
    _, s = _settings(tenant)
    assert _voucher("o", 40000, {**s, "voucher_percent": 25}, "x").params["value_paise"] == 10000


def test_tiny_order_escalates_instead_of_proposing(tenant):
    _, s = _settings(tenant)
    r = _voucher("o", 999, {**s, **WIDE}, "x")
    assert (r.action, r.outcome) == (None, "escalate")


def test_validation_rejects_a_voucher_above_the_order_total_and_shows_the_total(tenant):
    _, s = _settings(tenant)
    action = get_action("free_item_voucher")()
    facts = Facts(settings=s, order_total_paise=14900)

    def check(value):
        inp = action.Input(transaction_id=uuid.uuid4(), value_paise=value, reason="x")
        return action.validate(None, inp, facts)

    assert check(14900).ok and check(14900).checks["order_total_paise"] == 14900
    assert not check(15000).ok
