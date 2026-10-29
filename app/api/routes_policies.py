"""Read-only policy documents for the caller's own organization (S8.1).

Policy text is untrusted (hard rule 9): it is returned as data and the web app shows it as
plain text. Any signed-in role may read; RLS confines the session to one organization, so
another tenant's document is simply absent (404, hard rule 8).
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_tenant_context, not_found, tenant_db
from app.core.models import Brand, Location, PolicyChunk, PolicyDocument
from app.core.tenancy import TenantContext
from app.engine.remedy_choice import customer_language
from app.engine.rules_summary import RulesSummary, build_rules_summary

router = APIRouter(tags=["policies"])


class SectionOut(BaseModel):
    id: str  # the section number, e.g. "2.1"; stable for a given document version
    anchor: str  # in-page anchor "<doc>-<id>", used as /policies#<anchor>
    title: str
    text: str


class PolicyOut(BaseModel):
    id: str  # doc_key, e.g. late_delivery_v3
    title: str
    topic: str
    version: int
    in_force_from: date
    in_force_to: date | None
    scope: str  # "org", or the brand/location name it applies to
    sections: list[SectionOut]


class PolicySectionOut(SectionOut):
    document_id: str
    document_title: str
    version: int
    in_force_from: date
    in_force_to: date | None


def _number(section_ref: str) -> str:
    return section_ref.partition("#")[2]


def _order(number: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in number.split("."))


def anchor_for(doc_key: str, number: str) -> str:
    return f"{doc_key}-{number}"


def _scope_names(db: Session) -> tuple[dict, dict]:
    return (
        dict(db.execute(select(Brand.id, Brand.name)).all()),
        dict(db.execute(select(Location.id, Location.name)).all()),
    )


def _scope_label(doc: PolicyDocument, brands: dict, locations: dict) -> str:
    if doc.brand_id is not None:
        return brands.get(doc.brand_id, "brand")
    if doc.location_id is not None:
        return locations.get(doc.location_id, "location")
    return "org"


def _sections(db: Session, doc: PolicyDocument) -> list[SectionOut]:
    rows = db.execute(
        select(PolicyChunk.section_ref, PolicyChunk.heading, PolicyChunk.content).where(
            PolicyChunk.document_id == doc.id
        )
    ).all()
    out = [
        SectionOut(
            id=_number(ref),
            anchor=anchor_for(doc.doc_key, _number(ref)),
            title=heading,
            text=content,
        )
        for ref, heading, content in rows
    ]
    return sorted(out, key=lambda s: _order(s.id))


def _visible(doc: PolicyDocument, ctx: TenantContext) -> bool:
    """Staff scoped to some locations do not see another outlet's own policy."""
    if doc.location_id is None or not ctx.is_staff:
        return True
    return ctx.can_see_location(doc.location_id)


@router.get("/policies")
def list_policies(
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> list[PolicyOut]:
    """Documents in force today, each with its sections."""
    today = now.date()
    docs = db.scalars(
        select(PolicyDocument)
        .where(
            PolicyDocument.effective_from <= today,
            or_(PolicyDocument.effective_to.is_(None), PolicyDocument.effective_to > today),
        )
        .order_by(PolicyDocument.title, PolicyDocument.doc_key)
    ).all()
    brands, locations = _scope_names(db)
    return [
        PolicyOut(
            id=d.doc_key,
            title=d.title,
            topic=d.topic,
            version=d.version,
            in_force_from=d.effective_from,
            in_force_to=d.effective_to,
            scope=_scope_label(d, brands, locations),
            sections=_sections(db, d),
        )
        for d in docs
        if _visible(d, ctx)
    ]


@router.get("/policies/rules-summary")
def rules_summary(
    language: str | None = Query(default=None, max_length=8),
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> RulesSummary:
    """What a customer gets per issue category, in plain words, built in code from the tenant's
    pack and settings (S8.2). Staff also get each setting key and the level that set it. The
    language is the customer's own choice unless `language` names a supported one; unknown
    values fall back to English."""
    chosen = language or customer_language(db, ctx)
    return build_rules_summary(db, chosen, now, staff=ctx.is_staff)


@router.get("/policies/{doc_key}/{section}")
def get_policy_section(
    doc_key: str,
    section: str,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> PolicySectionOut:
    """One section by document and number. Older versions resolve too, so a decision made under
    them can still link to its source."""
    doc = db.scalar(select(PolicyDocument).where(PolicyDocument.doc_key == doc_key))
    if doc is None or not _visible(doc, ctx):
        raise not_found()
    found = next((s for s in _sections(db, doc) if s.id == section), None)
    if found is None:
        raise not_found()
    return PolicySectionOut(
        **found.model_dump(),
        document_id=doc.doc_key,
        document_title=doc.title,
        version=doc.version,
        in_force_from=doc.effective_from,
        in_force_to=doc.effective_to,
    )
