"""Every tenant's scenario set loads, is valid for its pack, and covers what E6.2 asks for."""

import pytest
import yaml

from app.core.tenant_config import load_tenant
from app.core.verticals import load_pack
from evals.scenarios import load_scenarios

REQUIRED_KINDS = {"hinglish", "missing_info", "wrong_claim", "injection", "out_of_policy"}


def _load(tenant):
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    return load_scenarios(tenant, cfg.slug, pack), pack


def test_scenarios_load_and_cover_every_category(tenant):
    scenarios, pack = _load(tenant)
    assert len(scenarios) >= 15
    assert {s.expect.category for s in scenarios} >= set(pack.issue_categories)
    assert {s.kind for s in scenarios} >= REQUIRED_KINDS


def test_about_a_fifth_is_held_out_and_three_are_live(tenant):
    scenarios, _ = _load(tenant)
    held = [s for s in scenarios if s.held_out]
    assert len(held) == 3
    live = [s for s in scenarios if "live" in s.tags]
    assert len(live) == 3 and not any(s.held_out for s in live)  # live checks use tuning data
    assert any(s.kind == "injection" for s in live)
    assert any(s.expect.outcome == "escalated" for s in live)
    assert any(s.expect.outcome == "proposed" for s in live)


def test_a_scenario_for_an_unknown_category_is_refused(tenant, tmp_path):
    scenarios, pack = _load(tenant)
    bad = scenarios[0].model_dump(exclude_none=True)
    bad["expect"]["category"] = "not_a_category"
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "x.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown category"):
        load_scenarios(tmp_path, scenarios[0].tenant, pack)


def test_expect_is_consistent():
    from evals.scenarios import Expect

    with pytest.raises(ValueError):
        Expect(category=None, outcome="proposed")  # a proposal needs an action
    with pytest.raises(ValueError):
        Expect(category=None, outcome="escalated", action="refund")
