"""Action + connector registries, wired to every tenant's pack and settings."""

import re
import uuid

import pytest

import app.actions  # noqa: F401  (registers built-ins)
import app.connectors  # noqa: F401
from app.actions.base import (
    Action,
    ActionInput,
    Risk,
    enabled_actions,
    get_action,
    register_action,
    registered_actions,
)
from app.connectors.base import connector_for, get_connector, registered_connectors
from app.core.settings_resolver import resolve
from app.core.tenancy import TenantContext
from app.core.tenant_config import load_tenant
from app.core.verticals import load_pack
from app.engine.proposals import ProposalError, parse_params
from mocks.base import Chaos
from mocks.registry import get_mock, merchant_id_for, reset_mocks


def _tenant_settings(tenant):
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    return cfg, pack, resolve(pack.settings, cfg.settings.org)


def test_every_pack_action_is_registered(tenant):
    _, pack, _ = _tenant_settings(tenant)
    enabled = enabled_actions(pack.actions)
    assert set(enabled) == set(pack.actions)
    assert all(issubclass(cls, Action) for cls in enabled.values())


def test_refund_is_high_risk_everywhere():
    assert get_action("refund").risk is Risk.HIGH


def test_duplicate_action_name_is_rejected():
    existing = get_action("refund")

    class Impostor(existing):
        pass

    with pytest.raises(ValueError, match="already registered"):
        register_action(Impostor)
    assert registered_actions()["refund"] is existing


def test_unknown_action_is_an_error():
    with pytest.raises(KeyError):
        enabled_actions(["refund", "wire_transfer"])


@pytest.mark.parametrize("kind", ["payment", "messaging", "orders", "vouchers"])
def test_tenant_settings_select_a_registered_connector(tenant, kind):
    _, _, settings = _tenant_settings(tenant)
    connector = connector_for(settings, kind)
    assert connector.kind == kind
    assert type(connector).name in registered_connectors()


def test_connector_kind_mismatch_is_an_error():
    with pytest.raises(TypeError):
        get_connector("mock_payment", "messaging")


def test_merchant_id_format_is_pinned():
    """Connectors and the dev chaos API must agree on this mapping."""
    tid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert merchant_id_for(tid) == "m_12345678123456781234567812345678"
    assert re.fullmatch(r"m_[0-9a-f]{32}", merchant_id_for(uuid.uuid4()))


@pytest.fixture
def ctx(tenant):
    yield TenantContext(
        tenant_id=uuid.uuid5(uuid.NAMESPACE_URL, tenant.name),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        role="hq_owner",
        brand_ids=frozenset(),
        location_ids=frozenset(),
    )
    reset_mocks()


def test_payment_connector_maps_provider_outcomes(ctx):
    pay = get_connector("mock_payment", "payment")
    merchant = merchant_id_for(ctx.tenant_id)
    assert pay.refund(ctx, "k1", "PAY-1", 100).status == "succeeded"
    get_mock("payment").set_chaos(Chaos(accept_then_timeout_rate=1.0), merchant)
    assert pay.refund(ctx, "k2", "PAY-1", 100).status == "unknown"  # applied, but no answer
    assert pay.find_refund(ctx, "k2").status == "succeeded"  # reconciliation finds the truth
    get_mock("payment").set_chaos(Chaos(transient_error_rate=1.0), merchant)
    assert pay.refund(ctx, "k3", "PAY-1", 100).status == "unavailable"
    assert pay.find_refund(ctx, "k3") is None  # nothing applied


def test_voucher_connector_maps_provider_outcomes(ctx):
    vc = get_connector("mock_vouchers", "vouchers")
    merchant = merchant_id_for(ctx.tenant_id)
    first = vc.issue(ctx, "v1", "CUST-1", "ORD-1", 100)
    assert first.status == "succeeded" and first.provider_reference
    assert vc.issue(ctx, "v1", "CUST-1", "ORD-1", 100) == first  # same key: same voucher
    get_mock("vouchers").set_chaos(Chaos(accept_then_timeout_rate=1.0), merchant)
    assert vc.issue(ctx, "v2", "CUST-1", "ORD-1", 100).status == "unknown"
    assert vc.find_voucher(ctx, "v2").status == "succeeded"
    get_mock("vouchers").set_chaos(Chaos(transient_error_rate=1.0), merchant)
    assert vc.issue(ctx, "v3", "CUST-1", "ORD-1", 100).status == "unavailable"
    assert vc.find_voucher(ctx, "v3") is None
    assert len(get_mock("vouchers").operations(merchant)) == 2


def test_connector_uses_the_contexts_tenant_account(ctx):
    pay = get_connector("mock_payment", "payment")
    pay.refund(ctx, "k1", "PAY-1", 100)
    assert len(get_mock("payment").operations(merchant_id_for(ctx.tenant_id))) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"transaction_id": str(uuid.uuid4()), "amount_paise": 349.0, "reason": "late"},
        {"transaction_id": str(uuid.uuid4()), "amount_paise": "34900", "reason": "late"},
        {"transaction_id": str(uuid.uuid4()), "amount_paise": 0, "reason": "late"},
        {"transaction_id": "not-a-uuid", "amount_paise": 100, "reason": "late"},
        {"transaction_id": str(uuid.uuid4()), "amount_paise": 100, "reason": "x", "extra": 1},
        {"transaction_id": str(uuid.uuid4()), "amount_paise": 100},
    ],
    ids=["float", "string_amount", "zero", "bad_uuid", "extra_field", "missing_reason"],
)
def test_refund_params_are_strict(params):
    with pytest.raises(ProposalError):
        parse_params(get_action("refund"), params)


def test_inputs_are_action_inputs():
    assert all(issubclass(cls.Input, ActionInput) for cls in registered_actions().values())
