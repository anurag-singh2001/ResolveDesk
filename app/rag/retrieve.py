"""Policy retrieval (PROJECT.md section 11).

1. Filter: the tenant (RLS on the caller's session), documents in effect on `as_of` (the
   order date, not today), and in scope: org, the order's brand, the order's location.
2. Override, section by section: within a topic a more specific document (location >
   brand > org) replaces the sections it defines (same section number); sections it doesn't
   define still come from the broader policy. Two documents at the top level for one topic
   is a conflict and is reported, not resolved.
3. Rank sections of the kept documents by cosine similarity and return the top k.

Similarity is never proof of eligibility; eligibility is enforced in code. Returned text is
untrusted: it may be quoted to an approver or summarised, never followed as instructions.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.models import PolicyChunk, PolicyDocument
from app.rag.embeddings import Embedder

SCOPE_RANK = {"org": 0, "brand": 1, "location": 2}


@dataclass(frozen=True)
class Citation:
    section_ref: str
    doc_key: str
    title: str
    topic: str
    version: int
    scope: str
    heading: str
    text: str
    score: float
    untrusted: bool = True  # hard rule 9


@dataclass(frozen=True)
class PolicyFindings:
    citations: list[Citation]
    missing: bool  # no policy in effect / in scope that matches
    conflicts: list[str] = field(default_factory=list)  # "topic: doc_a vs doc_b"
    considered: list[str] = field(default_factory=list)  # doc keys after override


def _scope(doc: PolicyDocument) -> str:
    if doc.location_id is not None:
        return "location"
    if doc.brand_id is not None:
        return "brand"
    return "org"


def search_policies(
    session: Session,
    embedder: Embedder,
    query: str,
    *,
    as_of: date,
    brand_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    topic: str | None = None,
    k: int = 4,
) -> PolicyFindings:
    """`topic` narrows the search; `missing` is then about that topic specifically."""
    in_scope = [PolicyDocument.brand_id.is_(None) & PolicyDocument.location_id.is_(None)]
    if brand_id is not None:
        in_scope.append(PolicyDocument.brand_id == brand_id)
    if location_id is not None:
        in_scope.append(PolicyDocument.location_id == location_id)
    query_docs = select(PolicyDocument).where(
        PolicyDocument.effective_from <= as_of,
        or_(PolicyDocument.effective_to.is_(None), PolicyDocument.effective_to > as_of),
        or_(*in_scope),
    )
    if topic is not None:
        query_docs = query_docs.where(PolicyDocument.topic == topic)
    docs = session.scalars(query_docs).all()
    if not docs:
        return PolicyFindings(citations=[], missing=True)

    # Section numbers per document, to apply overrides section by section.
    numbers: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    for chunk_id, doc_id, number in session.execute(
        select(PolicyChunk.id, PolicyChunk.document_id, PolicyChunk.meta["number"].astext).where(
            PolicyChunk.tenant_id.in_({d.tenant_id for d in docs}),
            PolicyChunk.document_id.in_([d.id for d in docs]),
        )
    ):
        numbers[doc_id].append((chunk_id, number))

    by_topic: dict[str, list[PolicyDocument]] = defaultdict(list)
    for d in docs:
        by_topic[d.topic].append(d)
    allowed: set[uuid.UUID] = set()
    considered: set[str] = set()
    conflicts: list[str] = []
    for name, group in sorted(by_topic.items()):
        # Most specific first. A section number is taken by the most specific document that
        # defines it; less specific documents still contribute the sections nobody overrode
        # (e.g. an org-wide allergen rule under a brand's own food-quality policy).
        ranked = sorted(group, key=lambda d: (-SCOPE_RANK[_scope(d)], d.doc_key))
        top = SCOPE_RANK[_scope(ranked[0])]
        tied = [d for d in ranked if SCOPE_RANK[_scope(d)] == top]
        if len(tied) > 1:
            conflicts.append(f"{name}: " + " vs ".join(d.doc_key for d in tied))
        claimed: set[str] = set()
        for rank in sorted({SCOPE_RANK[_scope(d)] for d in ranked}, reverse=True):
            level = [d for d in ranked if SCOPE_RANK[_scope(d)] == rank]
            level_numbers: set[str] = set()
            for d in level:
                kept = [(cid, n) for cid, n in numbers[d.id] if n not in claimed]
                if kept:
                    considered.add(d.doc_key)
                allowed.update(cid for cid, _ in kept)
                level_numbers.update(n for _, n in numbers[d.id])
            claimed |= level_numbers

    by_id = {d.id: d for d in docs}
    qvec = embedder.embed_query(query)
    distance = PolicyChunk.embedding.cosine_distance(qvec)
    rows = session.execute(
        select(PolicyChunk, distance.label("distance"))
        .where(
            PolicyChunk.tenant_id.in_({d.tenant_id for d in docs}),  # explicit, not only RLS
            PolicyChunk.id.in_(allowed),
        )
        .order_by(distance, PolicyChunk.section_ref)
        .limit(k)
    ).all()
    citations = [
        Citation(
            section_ref=chunk.section_ref,
            doc_key=by_id[chunk.document_id].doc_key,
            title=by_id[chunk.document_id].title,
            topic=by_id[chunk.document_id].topic,
            version=by_id[chunk.document_id].version,
            scope=_scope(by_id[chunk.document_id]),
            heading=chunk.heading,
            text=chunk.content,
            score=round(1.0 - float(dist), 4),
        )
        for chunk, dist in rows
    ]
    return PolicyFindings(
        citations=citations,
        missing=not citations,
        conflicts=conflicts,
        considered=sorted(considered),
    )
