import math

import pytest

from app.core.tenant_config import load_tenant
from app.rag.embeddings import HashEmbedder
from app.rag.policy_files import parse_scope, policy_files, split_sections


def test_every_policy_file_parses_with_unique_refs(tenant):
    files = policy_files(tenant)
    assert files, "each tenant ships policies"
    refs = [s.section_ref for f in files for s in f.sections]
    assert len(refs) == len(set(refs))
    assert all(f.sections for f in files)
    assert all(ref.split("#")[0] in {f.meta.id for f in files} for ref in refs)


def test_policy_scopes_point_at_the_tenants_own_brands_and_locations(tenant):
    cfg = load_tenant(tenant)
    brands = {b.slug for b in cfg.brands}
    locations = {loc.slug for loc in cfg.locations}
    for f in policy_files(tenant):
        kind, slug = parse_scope(f.meta.scope)
        if kind == "brand":
            assert slug in brands, f.meta.id
        if kind == "location":
            assert slug in locations, f.meta.id


def test_versions_of_a_topic_do_not_overlap(tenant):
    by_topic = {}
    for f in policy_files(tenant):
        by_topic.setdefault((f.meta.topic, f.meta.scope), []).append(f.meta)
    for metas in by_topic.values():
        metas.sort(key=lambda m: m.effective_from)
        for earlier, later in zip(metas, metas[1:], strict=False):
            assert earlier.effective_to is not None and earlier.effective_to <= later.effective_from


def test_sections_split_on_numbered_headings():
    body = "# Title\nintro\n## 1. Scope\nAll orders.\n### 1.1 Detail\nMore.\n## 2 Remedy\nRefund."
    sections = split_sections("doc_v1", body)
    assert [(s.section_ref, s.heading) for s in sections] == [
        ("doc_v1#1", "Scope"),
        ("doc_v1#1.1", "Detail"),
        ("doc_v1#2", "Remedy"),
    ]
    assert sections[0].content == "All orders."


@pytest.mark.parametrize("bad", ["brand:", "outlet:baner", "everyone"])
def test_bad_scopes_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_scope(bad)


def test_hash_embedder_is_deterministic_normalised_and_word_sensitive():
    e = HashEmbedder()
    a, b, c = e.embed(["refund missing item", "refund missing item", "late delivery voucher"])
    assert a == b and len(a) == 384
    assert math.isclose(sum(x * x for x in a), 1.0)
    cos = sum(x * y for x, y in zip(a, c, strict=True))
    assert cos < sum(x * y for x, y in zip(a, b, strict=True))


def test_escalation_amounts_in_refund_policies_match_settings(tenant):
    """Prose figures must not drift from the limits code enforces."""
    import re

    from app.core.settings_resolver import resolve
    from app.core.verticals import load_pack

    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    checked = 0
    for f in policy_files(tenant):
        if f.meta.topic != "refunds":
            continue
        kind, slug = parse_scope(f.meta.scope)
        layers = [cfg.settings.org]
        if kind == "brand":
            layers.append(cfg.settings.brands.get(slug, {}))
        if kind == "location":
            layers += [{}, cfg.settings.locations.get(slug, {})]
        limit = resolve(pack.settings, *layers)["refund_without_escalation_paise"]
        text = " ".join(s.content for s in f.sections)
        for rupees in re.findall(r"above ₹(\d[\d,]*)", text):
            assert int(rupees.replace(",", "")) * 100 == limit, (f.meta.id, rupees, limit)
            checked += 1
    assert checked, "each tenant's refund policy states its escalation limit"
