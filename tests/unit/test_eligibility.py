"""Deterministic eligibility from Facts, against each tenant's real effective settings."""

import uuid
from types import SimpleNamespace

import pytest

from app.actions.base import Facts, get_action
from app.core.money import percent_of
from app.core.settings_resolver import resolve
from app.core.tenancy import TenantContext
from app.core.tenant_config import load_tenant
from app.core.verticals import load_pack
from app.engine import resolver
from app.engine.eligibility import is_aggregator_order

CTX = TenantContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "hq_owner", frozenset(), frozenset())
TOTAL = 69_800


@pytest.fixture
def settings(tenant):
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    loc = cfg.locations[0]
    return resolve(
        pack.settings,
        cfg.settings.org,
        cfg.settings.brands.get(loc.brands[0], {}),
        cfg.settings.locations.get(loc.slug, {}),
    )


def _refund(amount, settings, refundable=TOTAL):
    action = get_action("refund")()
    inp = action.Input(transaction_id=uuid.uuid4(), amount_paise=amount, reason="late")
    facts = Facts(settings=settings, order_total_paise=TOTAL, refundable_paise=refundable)
    return action.validate(CTX, inp, facts)


def test_refund_up_to_the_percent_cap_is_eligible(settings):
    cap = percent_of(TOTAL, settings["refund_max_percent"])
    result = _refund(cap, settings)
    assert result.ok, result.errors
    assert result.checks["max_by_percent_paise"] == cap


def test_refund_above_the_percent_cap_is_not(settings):
    cap = percent_of(TOTAL, settings["refund_max_percent"])
    if cap >= TOTAL:
        pytest.skip("this tenant allows refunds up to the full order")
    assert not _refund(cap + 1, settings).ok


def test_refund_above_the_refundable_balance_is_not(settings):
    result = _refund(100, settings, refundable=99)
    assert not result.ok
    assert "refundable balance" in result.errors[0]


def test_aggregator_only_channel_blocks_refunds(settings):
    result = _refund(100, {**settings, "refund_channel": "aggregator_only"})
    assert not result.ok
    assert "aggregator" in result.errors[0]


def test_needs_hq_above_the_escalation_limit(settings):
    limit = settings["refund_without_escalation_paise"]
    total = limit * 4
    action = get_action("refund")()
    facts = Facts(
        settings={**settings, "refund_max_percent": 100},
        order_total_paise=total,
        refundable_paise=total,
    )
    over = action.validate(
        CTX, action.Input(transaction_id=uuid.uuid4(), amount_paise=limit + 1, reason="x"), facts
    )
    at = action.validate(
        CTX, action.Input(transaction_id=uuid.uuid4(), amount_paise=limit, reason="x"), facts
    )
    assert over.checks["needs_hq"] and not at.checks["needs_hq"]


def test_voucher_limits_and_auto_approval(settings):
    action = get_action("free_item_voucher")()
    # A voucher is now checked against the order total (S7.8, fail closed when unknown), so the
    # fixture order is larger than any cap and only the caps are under test here.
    facts = Facts(settings=settings, order_total_paise=settings["voucher_max_paise"] * 10)
    auto_cap, cap = settings["voucher_auto_approve_max_paise"], settings["voucher_max_paise"]

    def voucher(value):
        return action.Input(transaction_id=uuid.uuid4(), value_paise=value, reason="x")

    assert action.can_auto_approve(voucher(auto_cap), facts)
    assert not action.can_auto_approve(voucher(auto_cap + 1), facts)
    assert action.validate(CTX, voucher(cap), facts).ok
    assert not action.validate(CTX, voucher(cap + 1), facts).ok


def test_refunds_are_never_auto_approvable():
    assert get_action("refund").auto_approvable is False


def test_audit_redaction_is_case_insensitive_and_covers_free_text():
    from app.core.audit import redact

    out = redact(
        {
            "customer_phone": "98",
            "Email": "a@b",
            "note": "call me",
            "to": "+91",
            "amount_paise": 100,
            "nested": [{"display_name": "R"}],
        }
    )
    assert out == {
        "customer_phone": "[redacted]",
        "Email": "[redacted]",
        "note": "[redacted]",
        "to": "[redacted]",
        "amount_paise": 100,
        "nested": [{"display_name": "[redacted]"}],
    }


@pytest.mark.parametrize("source", ["swiggy", "SWIGGY", " Zomato "])
def test_an_override_cannot_hide_a_delivery_app(settings, source):
    order = SimpleNamespace(source=source)
    for hostile in ([], None, ["only_other"]):
        assert is_aggregator_order(order, {**settings, "aggregator_order_sources": hostile})


def test_a_setting_can_add_a_delivery_app_and_own_channels_stay_own(settings):
    extra = {**settings, "aggregator_order_sources": ["Dunzo"]}
    assert is_aggregator_order(SimpleNamespace(source="dunzo"), extra)
    assert not is_aggregator_order(SimpleNamespace(source="pickup_app"), extra)
    assert not is_aggregator_order(SimpleNamespace(source=None), extra)


@pytest.mark.parametrize("option", ["late_tiers", "refund_missing"])
def test_no_rule_returns_a_refund_for_an_order_the_delivery_app_refunds(
    settings, monkeypatch, option
):
    """Late tiers and missing items go through the same guard as the refund option."""
    refund = resolver.Remedy("refund", {"amount_paise": 100}, "x", "proposed")
    monkeypatch.setattr(resolver, "_apply_rule", lambda *a, **k: refund)
    own = SimpleNamespace(settings={**settings, "refund_channel": "tenant_gateway"})
    assert resolver._apply(None, None, own, "c", option).action == "refund"
    app = SimpleNamespace(settings={**settings, "refund_channel": "aggregator_only"})
    got = resolver._apply(None, None, app, "c", option)
    assert got.action is None and got.outcome == "escalate"
