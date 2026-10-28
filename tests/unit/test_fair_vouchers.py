"""S7.8: a voucher never exceeds what the customer paid, and scales with the order."""

import uuid
from types import SimpleNamespace

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


def test_a_stored_pack_without_voucher_percent_still_works_as_100_percent(tenant):
    _, s = _settings(tenant)
    old = {k: v for k, v in {**s, **WIDE}.items() if k != "voucher_percent"}
    assert _voucher("o", 14900, old, "x").params["value_paise"] == 14900


def test_a_tenant_override_above_100_percent_resolves_to_100(tenant):
    pack = load_pack(load_tenant(tenant).vertical_pack)
    assert resolve(pack.settings, {"voucher_percent": 150})["voucher_percent"] == 100


def test_validation_fails_closed_when_the_order_total_is_unknown(tenant):
    _, s = _settings(tenant)
    action = get_action("free_item_voucher")()
    inp = action.Input(transaction_id=uuid.uuid4(), value_paise=1000, reason="x")
    result = action.validate(None, inp, Facts(settings=s))
    assert not result.ok and "order total unknown" in result.errors[0]


def test_the_agent_path_rejects_a_voucher_above_the_order_total(tenant):
    from app.engine.graph import _check_draft
    from app.engine.resolver import Remedy

    _, s = _settings(tenant)
    order_id = str(uuid.uuid4())
    facts = Facts(settings=s, order_total_paise=14900)
    # The ceiling is generous on purpose: only the order-total check can reject this.
    ceiling = Remedy("free_item_voucher", {"value_paise": 30000}, "x", "proposed")

    def check(value):
        draft = SimpleNamespace(
            action="free_item_voucher",
            params={"transaction_id": order_id, "value_paise": value, "reason": "x"},
            citations=["s#1"],
        )
        actions = {"free_item_voucher": None}
        return _check_draft(draft, actions, facts, {"s#1"}, order_id, ceiling)

    assert check(14900) == []
    assert any("what the customer paid" in e for e in check(15000))
