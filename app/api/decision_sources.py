"""Where a decision came from (S8.3): the rule that set the amount, and the policy sections cited.

Everything shown is built in code from our own tables and fixed templates:
- the remedy line comes from the structured `basis` codes the resolver stored on the proposal
  (no model text, hard rule 7);
- a citation shows the document title and section number from our policy table. The text of a
  policy section, or any quote a model wrote, is never returned here (hard rule 9);
- links resolve inside the caller's tenant only (RLS), and a section or document the caller
  cannot see counts as changed, so nothing leaks about records outside their scope.
"""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes_policies import _number, _visible, anchor_for
from app.core.i18n import t
from app.core.models import ActionProposal, PolicyChunk, PolicyDocument
from app.core.money import format_inr
from app.core.tenancy import TenantContext


class SourceOut(BaseModel):
    doc_key: str | None
    version: int | None
    document_title: str | None  # from our policy table, None when the document is gone
    section_id: str | None  # the section number, None when the section changed
    href: str  # /policies#<anchor>; the document (or the page) when the section changed
    section_changed: bool
    policy_revised: bool = False  # the section exists, in a newer version of the document
    note: str | None  # the fixed "section changed" line, in the reader's language


class DecisionSourcesOut(BaseModel):
    basis: list[str]  # which rule set the amount, one plain line each
    sources: list[SourceOut]


def basis_lines(proposal: ActionProposal, language: str) -> list[str]:
    """Plain lines from the stored basis codes; unknown or malformed entries are skipped."""
    stored = proposal.validation if isinstance(proposal.validation, dict) else {}
    out: list[str] = []
    for item in stored.get("basis") or []:
        if not isinstance(item, dict) or not isinstance(item.get("code"), str):
            continue
        p = item.get("params") if isinstance(item.get("params"), dict) else {}
        try:
            out.extend(_render(item["code"], p, language))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _render(code: str, p: dict, lang: str) -> list[str]:
    if code == "voucher_order_total":
        percent = p.get("percent", 100)
        if percent == 100:
            return [t("basis.voucher_order_total", lang)]
        return [t("basis.voucher_order_percent", lang, percent=int(percent))]
    if code == "voucher_cap":
        return [t("basis.voucher_cap", lang, cap=format_inr(int(p["cap_paise"])))]
    if code == "late_tier":
        return [t("basis.late_tier", lang, minutes=int(p["minutes"]), tier=int(p["tier_minutes"]))]
    if code in ("refund_percent", "refund_choice"):
        lines = [t(f"basis.{code}", lang, percent=int(p["percent"]))]
        if p.get("capped") is True:
            lines.append(t("basis.capped_refundable", lang))
        return lines
    if code == "refund_missing":
        lines = [t("basis.refund_missing", lang)]
        if p.get("capped") is True:
            lines.append(t("basis.refund_missing_capped", lang))
        return lines
    if code == "approver_set":
        return [t("basis.approver_set", lang)]
    return []


def decision_sources(
    db: Session, ctx: TenantContext, proposal: ActionProposal, language: str
) -> DecisionSourcesOut:
    """The remedy basis and the cited sections of one proposal, for a reader already allowed to
    see its case."""
    out: list[SourceOut] = []
    seen: set[tuple] = set()
    raw = proposal.citations if isinstance(proposal.citations, list) else []
    for c in raw:
        if not isinstance(c, dict) or not isinstance(c.get("section_ref"), str):
            continue
        doc_key = c["doc_key"] if isinstance(c.get("doc_key"), str) else None
        version = c.get("version") if type(c.get("version")) is int else None
        if (doc_key, c["section_ref"]) in seen:
            continue
        seen.add((doc_key, c["section_ref"]))
        out.append(_resolve(db, ctx, doc_key, c["section_ref"], version, language))
    return DecisionSourcesOut(basis=basis_lines(proposal, language), sources=out)


def _resolve(
    db: Session,
    ctx: TenantContext,
    doc_key: str | None,
    section_ref: str,
    version: int | None,
    language: str,
) -> SourceOut:
    doc = (
        db.scalar(select(PolicyDocument).where(PolicyDocument.doc_key == doc_key))
        if doc_key
        else None
    )  # RLS: another tenant's document is simply absent
    if doc is None or not _visible(doc, ctx):
        return SourceOut(
            doc_key=None, version=version, document_title=None, section_id=None,
            href="/policies", section_changed=True, note=t("source.changed", language),
        )  # fmt: skip
    number = _number(section_ref)
    exists = (
        db.scalar(
            select(PolicyChunk.id).where(
                PolicyChunk.document_id == doc.id, PolicyChunk.section_ref == section_ref
            )
        )
        is not None
    )
    if not exists or not number:
        return SourceOut(
            doc_key=doc.doc_key, version=version or doc.version, document_title=doc.title,
            section_id=None, href=f"/policies#{doc.doc_key}", section_changed=True,
            note=t("source.changed", language),
        )  # fmt: skip
    # The section still exists, but the document was revised after the decision: link to the
    # current section and say the policy has changed.
    revised = version is not None and version != doc.version
    return SourceOut(
        doc_key=doc.doc_key, version=version or doc.version, document_title=doc.title,
        section_id=number, href=f"/policies#{anchor_for(doc.doc_key, number)}",
        section_changed=False, policy_revised=revised,
        note=t("source.version_changed", language) if revised else None,
    )  # fmt: skip
