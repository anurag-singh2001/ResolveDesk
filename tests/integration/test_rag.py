"""Versioned, scoped policy retrieval for every tenant (PROJECT.md section 11)."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.models import Brand, Location
from app.core.tenancy import tenant_id_for
from app.rag.embeddings import HashEmbedder
from app.rag.ingest import ingest_policies
from app.rag.policy_files import parse_scope, policy_files
from app.rag.retrieve import search_policies

EMBEDDER = HashEmbedder()


@pytest.fixture(scope="session")
def policies(app_engine, seeded):
    from app.core.tenant_config import tenant_dirs

    for folder in tenant_dirs():
        ingest_policies(app_engine, seeded[folder.name].slug, folder, EMBEDDER)
    return seeded


def _ids(engine, slug):
    with tenant_session(tenant_id_for(slug), engine) as s:
        brands = dict(s.execute(select(Brand.slug, Brand.id)).all())
        locations = dict(s.execute(select(Location.slug, Location.id)).all())
    return brands, locations


def _search(engine, slug, query, **kw):
    with tenant_session(tenant_id_for(slug), engine) as s:
        return search_policies(s, EMBEDDER, query, **kw)


def test_ingest_is_idempotent(app_engine, policies, tenant):
    again = ingest_policies(app_engine, policies[tenant.name].slug, tenant, EMBEDDER)
    assert again.written == 0 and again.unchanged == again.documents and again.removed == 0


def test_the_order_date_picks_the_version(app_engine, policies, tenant):
    slug = policies[tenant.name].slug
    files = [f.meta for f in policy_files(tenant) if f.meta.scope == "org"]
    topics = {m.topic for m in files if sum(x.topic == m.topic for x in files) > 1}
    if not topics:
        pytest.skip("no topic with several versions in this tenant")
    for meta in (m for m in files if m.topic in topics):
        found = _search(app_engine, slug, meta.title, as_of=meta.effective_from)
        same_topic = [
            k for k in found.considered if k in {m.id for m in files if m.topic == meta.topic}
        ]
        assert same_topic == [meta.id], (meta.id, found.considered)
        cited = {c.doc_key for c in found.citations if c.topic == meta.topic}
        assert cited <= {meta.id}


def test_scoped_policy_overrides_org_only_in_its_scope(app_engine, policies, tenant):
    slug = policies[tenant.name].slug
    brands, locations = _ids(app_engine, slug)
    metas = [f.meta for f in policy_files(tenant)]
    scoped = [m for m in metas if m.scope != "org"]
    if not scoped:
        pytest.skip("no brand/location policy in this tenant")
    for m in scoped:
        kind, scope_slug = parse_scope(m.scope)
        org_versions = {x.id for x in metas if x.topic == m.topic and x.scope == "org"}
        here = (
            {"brand_id": brands[scope_slug]}
            if kind == "brand"
            else {"location_id": locations[scope_slug]}
        )
        inside = _search(
            app_engine, slug, m.title, as_of=m.effective_from + timedelta(days=300), **here
        )
        assert m.id in inside.considered
        # (which org sections still apply is checked section by section in the next test)
        outside = _search(app_engine, slug, m.title, as_of=m.effective_from + timedelta(days=300))
        assert m.id not in outside.considered
        if org_versions:
            assert org_versions & set(outside.considered)


def test_nothing_in_effect_is_reported_missing(app_engine, policies, tenant):
    slug = policies[tenant.name].slug
    earliest = min(f.meta.effective_from for f in policy_files(tenant))
    found = _search(app_engine, slug, "refund", as_of=earliest - timedelta(days=1))
    assert found.missing and found.citations == []


def test_other_tenants_policies_are_never_returned(app_engine, policies, tenant):
    from app.core.tenant_config import tenant_dirs

    slug = policies[tenant.name].slug
    own = {f.meta.id for f in policy_files(tenant)}
    for other in (p for p in tenant_dirs() if p != tenant):
        for meta in (f.meta for f in policy_files(other)):
            found = _search(app_engine, slug, meta.title, as_of=meta.effective_from, k=20)
            assert set(found.considered) <= own
            assert {c.doc_key for c in found.citations} <= own


def test_citations_carry_refs_and_are_marked_untrusted(app_engine, policies, tenant):
    slug = policies[tenant.name].slug
    latest = max(f.meta.effective_from for f in policy_files(tenant))
    found = _search(app_engine, slug, "refund approval limit", as_of=latest)
    assert found.citations and not found.missing
    for c in found.citations:
        assert c.untrusted and c.section_ref.startswith(f"{c.doc_key}#")
        assert -1.0 <= c.score <= 1.0


def test_org_sections_a_scoped_policy_does_not_override_still_apply(app_engine, policies, tenant):
    """e.g. an org-wide allergen rule must survive a brand's own food-quality policy."""
    slug = policies[tenant.name].slug
    brands, locations = _ids(app_engine, slug)
    files = policy_files(tenant)
    for scoped in (f for f in files if f.meta.scope != "org"):
        kind, scope_slug = parse_scope(scoped.meta.scope)
        here = (
            {"brand_id": brands[scope_slug]}
            if kind == "brand"
            else {"location_id": locations[scope_slug]}
        )
        as_of = scoped.meta.effective_from + timedelta(days=300)
        overridden = {s.number for s in scoped.sections}
        for org in (
            f for f in files if f.meta.topic == scoped.meta.topic and f.meta.scope == "org"
        ):
            if not (
                org.meta.effective_from <= as_of
                and (org.meta.effective_to is None or as_of < org.meta.effective_to)
            ):
                continue
            found = _search(
                app_engine,
                slug,
                scoped.meta.title,
                as_of=as_of,
                topic=scoped.meta.topic,
                k=50,
                **here,
            )
            cited = {c.section_ref for c in found.citations}
            for sec in org.sections:
                if sec.number in overridden:
                    assert sec.section_ref not in cited, sec.section_ref
                else:
                    assert sec.section_ref in cited, sec.section_ref  # still in force


def test_unknown_topic_is_reported_missing(app_engine, policies, tenant):
    slug = policies[tenant.name].slug
    latest = max(f.meta.effective_from for f in policy_files(tenant))
    found = _search(app_engine, slug, "anything", as_of=latest, topic="no_such_topic")
    assert found.missing and found.citations == []


def test_reingest_applies_changes_removals_and_model_switches(
    app_engine, policies, tenant, tmp_path
):
    import shutil

    from app.core.models import PolicyChunk, PolicyDocument

    slug = policies[tenant.name].slug
    work = tmp_path / tenant.name
    shutil.copytree(tenant / "policies", work / "policies")
    files = sorted((work / "policies").rglob("*.md"))
    gone, changed = files[0], files[1]
    gone_id = policy_files(tenant)[0].meta.id
    gone.unlink()
    text = changed.read_text(encoding="utf-8")
    # drop the last section of the changed file
    head, _, _ = text.rpartition("\n#")
    changed.write_text(head + "\n", encoding="utf-8")
    try:
        stats = ingest_policies(app_engine, slug, work, EMBEDDER)
        assert stats.removed == 1 and stats.written == 1
        with tenant_session(tenant_id_for(slug), app_engine) as s:
            keys = set(s.scalars(select(PolicyDocument.doc_key)))
            refs = set(s.scalars(select(PolicyChunk.section_ref)))
        assert gone_id not in keys
        expected = {sec.section_ref for f in policy_files(work) for sec in f.sections}
        assert refs == expected  # no stale chunk survives a removed file or section

        class OtherModel(HashEmbedder):
            model_id = "other-model"

        switched = ingest_policies(app_engine, slug, work, OtherModel())
        assert switched.written == switched.documents  # new model: everything re-embedded
    finally:
        ingest_policies(app_engine, slug, tenant, EMBEDDER)  # back to the real folder
