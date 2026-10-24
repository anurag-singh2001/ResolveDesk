"""Policy markdown files: front matter + numbered sections.

    ---
    id: late_delivery_v3
    title: Late delivery policy
    topic: late_delivery
    version: 3
    effective_from: 2026-09-01
    effective_to: 2026-12-31     # optional, exclusive
    scope: org | brand:<slug> | location:<slug>
    ---
    ## 2. Remedies
    ### 2.1 More than 45 minutes late
    ...

Each numbered heading becomes one section with section_ref `<id>#<number>` (2.1).
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

HEADING = re.compile(r"^(#{2,4})\s+(\d+(?:\.\d+)*)\.?\s+(.*)$")
# Front matter between lines that are exactly "---" (a "---" inside a value can't split it).
FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*\r?$\n?", re.S | re.M)


class PolicyMeta(BaseModel):
    id: str
    title: str
    topic: str
    version: int
    effective_from: date
    effective_to: date | None = None
    scope: str = "org"
    # Scoped policies list the org section numbers they replace; reusing any other org number
    # is an error (tests/unit/test_policy_files.py), so a clause is never hidden by accident.
    overrides: list[str] = []

    @model_validator(mode="after")
    def _check(self) -> "PolicyMeta":
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError(f"{self.id}: effective_to must be after effective_from")
        parse_scope(self.scope)  # raises on a malformed scope
        return self


def parse_scope(scope: str) -> tuple[Literal["org", "brand", "location"], str | None]:
    if scope == "org":
        return "org", None
    kind, _, slug = scope.partition(":")
    if kind not in ("brand", "location") or not slug:
        raise ValueError(f"scope must be org, brand:<slug> or location:<slug>, got {scope!r}")
    return kind, slug  # type: ignore[return-value]


@dataclass(frozen=True)
class Section:
    section_ref: str
    number: str
    heading: str
    content: str


@dataclass(frozen=True)
class PolicyFile:
    meta: PolicyMeta
    sections: list[Section]
    source_uri: str
    content_hash: str


def parse_policy(path: Path, root: Path) -> PolicyFile:
    text = path.read_text(encoding="utf-8")
    m = FRONT_MATTER.match(text)
    if m is None:
        raise ValueError(f"{path.name}: missing front matter")
    front, body = m.group(1), text[m.end() :]
    meta = PolicyMeta.model_validate(yaml.safe_load(front))
    return PolicyFile(
        meta=meta,
        sections=split_sections(meta.id, body),
        source_uri=path.relative_to(root).as_posix(),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def split_sections(doc_id: str, body: str) -> list[Section]:
    """One section per numbered heading; its text runs until the next numbered heading."""
    sections: list[Section] = []
    current: tuple[str, str] | None = None
    lines: list[str] = []

    def flush() -> None:
        if current is not None:
            content = "\n".join(lines).strip()
            if content:
                number, heading = current
                sections.append(Section(f"{doc_id}#{number}", number, heading, content))

    for line in body.splitlines():
        m = HEADING.match(line.strip())
        if m:
            flush()
            current, lines = (m.group(2), m.group(3).strip()), []
        elif current is not None:
            lines.append(line)
    flush()
    seen: set[str] = set()
    for sec in sections:
        if sec.number in seen:
            raise ValueError(f"{doc_id}: section {sec.number} appears twice")
        seen.add(sec.number)
    return sections


def policy_files(tenant_folder: Path) -> list[PolicyFile]:
    root = tenant_folder / "policies"
    if not root.is_dir():
        return []
    return [parse_policy(p, tenant_folder) for p in sorted(root.rglob("*.md"))]
