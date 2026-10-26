"""Ingest a tenant's policy files into policy_documents + policy_chunks.

Idempotent: a file whose content hash is unchanged is skipped; a changed file replaces its
document (chunks cascade); a file removed from the folder removes its document. Embedding
happens before the transaction opens, so the transaction stays short.
"""

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, delete, select, text

from app.core.db import tenant_session
from app.core.models import Brand, Location, PolicyChunk, PolicyDocument
from app.core.tenancy import NAMESPACE, tenant_id_for
from app.rag.embeddings import Embedder
from app.rag.policy_files import PolicyFile, parse_scope, policy_files


@dataclass(frozen=True)
class IngestStats:
    documents: int
    written: int
    unchanged: int
    removed: int
    chunks: int


def _doc_id(tenant_id: uuid.UUID, key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{tenant_id}:policy:{key}")


def ingest_policies(
    engine: Engine, tenant_slug: str, folder: Path, embedder: Embedder
) -> IngestStats:
    """Admin/seed path: the tenant comes from the folder being loaded, never from a request."""
    files = policy_files(folder)
    keys = [f.meta.id for f in files]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{tenant_slug}: duplicate policy ids")
    tid = tenant_id_for(tenant_slug)

    with tenant_session(tid, engine) as s:
        brands = dict(s.execute(select(Brand.slug, Brand.id).where(Brand.tenant_id == tid)).all())
        locations = dict(
            s.execute(select(Location.slug, Location.id).where(Location.tenant_id == tid)).all()
        )
        existing = _existing(s, tid)
    scopes = {f.meta.id: _scope_ids(f, brands, locations) for f in files}
    stamps = {f.meta.id: _stamp(f, embedder.model_id, scopes[f.meta.id]) for f in files}
    to_write = [f for f in files if existing.get(f.meta.id) != stamps[f.meta.id]]
    # Embed before the write transaction (CPU-bound; keeps the transaction short).
    vectors = embedder.embed([_chunk_text(f, sec) for f in to_write for sec in f.sections])

    removed = written = 0
    with tenant_session(tid, engine) as s:
        # One ingest per tenant at a time; re-read inside the lock so a concurrent run that
        # already wrote the same content isn't repeated or overwritten.
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"policies:{tid}"})
        existing = _existing(s, tid)
        stale = set(existing) - set(keys)
        if stale:
            removed = s.execute(
                delete(PolicyDocument).where(
                    PolicyDocument.tenant_id == tid, PolicyDocument.doc_key.in_(stale)
                )
            ).rowcount
        it = iter(vectors)
        for f in to_write:
            chunk_vectors = [next(it) for _ in f.sections]
            if existing.get(f.meta.id) == stamps[f.meta.id]:
                continue  # written meanwhile by another run
            doc_id = _doc_id(tid, f.meta.id)
            # Replace the whole document: its old chunks go with it (cascade), so a removed
            # or renumbered section can't linger.
            s.execute(
                delete(PolicyDocument).where(
                    PolicyDocument.tenant_id == tid, PolicyDocument.id == doc_id
                )
            )
            brand_id, location_id = scopes[f.meta.id]
            s.add(
                PolicyDocument(
                    id=doc_id,
                    tenant_id=tid,
                    doc_key=f.meta.id,
                    title=f.meta.title,
                    topic=f.meta.topic,
                    version=f.meta.version,
                    brand_id=brand_id,
                    location_id=location_id,
                    effective_from=f.meta.effective_from,
                    effective_to=f.meta.effective_to,
                    source_uri=f.source_uri,
                    content_hash=stamps[f.meta.id],
                )
            )
            s.flush()
            for sec, vector in zip(f.sections, chunk_vectors, strict=True):
                s.add(
                    PolicyChunk(
                        tenant_id=tid,
                        document_id=doc_id,
                        section_ref=sec.section_ref,
                        heading=sec.heading,
                        content=sec.content,
                        embedding=vector,
                        meta={"number": sec.number, "model": embedder.model_id},
                    )
                )
            written += 1
    return IngestStats(
        documents=len(files),
        written=written,
        unchanged=len(files) - len(to_write),
        removed=removed,
        chunks=sum(len(f.sections) for f in to_write),
    )


def _existing(session, tid) -> dict[str, str]:
    return dict(
        session.execute(
            select(PolicyDocument.doc_key, PolicyDocument.content_hash).where(
                PolicyDocument.tenant_id == tid
            )
        ).all()
    )


def _stamp(f: PolicyFile, model_id: str, scope_ids) -> str:
    """What makes stored vectors current: the file, the embedding model, the resolved scope.
    A run with another embedder (e.g. tests' hash vectors) is never mistaken for 'unchanged'."""
    material = f"{f.content_hash}|{model_id}|{scope_ids[0]}|{scope_ids[1]}"
    return hashlib.sha256(material.encode()).hexdigest()


def _chunk_text(f: PolicyFile, section) -> str:
    # The title and heading help similarity; the stored content stays the section text alone.
    return f"{f.meta.title}. {section.heading}. {section.content}"


def _scope_ids(f: PolicyFile, brands: dict, locations: dict):
    kind, slug = parse_scope(f.meta.scope)
    if kind == "brand":
        if slug not in brands:
            raise ValueError(f"{f.meta.id}: unknown brand {slug!r}")
        return brands[slug], None
    if kind == "location":
        if slug not in locations:
            raise ValueError(f"{f.meta.id}: unknown location {slug!r}")
        return None, locations[slug]
    return None, None
