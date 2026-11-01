"""Scenario files: tenants/<slug>/scenarios/*.yaml, one scenario per file (PROJECT.md 13).

A scenario names an order *selector* (e.g. the most late delivery, an order with a missing
item), never a hard-coded id, so it survives a reseed. `expect` is the outcome the tenant's
own rules call for; scoring is deterministic code (evals/metrics.py).
"""

import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.verticals import VerticalPack

Selector = Literal["latest", "most_late", "late_between", "on_time", "shortfall", "flagged", "none"]
Outcome = Literal["proposed", "escalated", "awaiting_info"]
Kind = Literal[
    "plain", "phrasing", "hinglish", "missing_info", "wrong_claim", "injection", "out_of_policy"
]


class OrderSelector(BaseModel):
    """Which seeded order the case is about. Orders already used by an earlier scenario in
    the same pass, or that had a case before the eval started, are skipped.

    - latest: newest completed order
    - most_late: the largest delay between promised and completed
    - late_between: newest order delayed by min_minutes..max_minutes
    - on_time: newest order completed on or before its promise
    - shortfall: newest order with an item short (one is made on the newest order if none)
    - flagged: newest order whose fulfilment has attribute `flag` true (else latest)
    - none: the case has no order (the customer must say which)

    `placed_on` moves the picked order to that business date (intervals kept), for rules
    dated after the generated history ends (e.g. late tiers in force from a later date).
    """

    model_config = ConfigDict(extra="forbid")
    select: Selector
    min_minutes: int | None = None
    max_minutes: int | None = None
    flag: str | None = None
    placed_on: date | None = None

    @model_validator(mode="after")
    def _params(self) -> "OrderSelector":
        if self.select == "late_between" and (self.min_minutes is None or self.max_minutes is None):
            raise ValueError("late_between needs min_minutes and max_minutes")
        if self.select == "flagged" and not self.flag:
            raise ValueError("flagged needs flag")
        return self


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None  # what the case should be classified as; None: no classification
    outcome: Outcome
    action: str | None = None  # the proposal's action; None: no proposal
    # proposals only: "exact" = the business rule's amount, "within" = at most that amount
    amount: Literal["exact", "within"] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "Expect":
        if (self.outcome == "proposed") != (self.action is not None):
            raise ValueError("an action is expected exactly when the outcome is 'proposed'")
        if self.amount and self.action is None:
            raise ValueError("amount needs an action")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tenant: str
    kind: Kind = "plain"
    # Optional label for the per-language report (e.g. "en", "hi"); reporting only, never scored.
    language: str | None = Field(default=None, max_length=16, pattern=r"^[a-z][a-z-]*$")
    message: str = Field(min_length=1)
    order: OrderSelector
    expect: Expect
    held_out: bool = False
    tags: list[str] = Field(default_factory=list)  # e.g. "live": also in pytest -m live
    note: str = ""


MAX_SCENARIO_BYTES = 16_000  # one scenario is a few lines; bigger input is refused unparsed
SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")  # also the file name: no dots, no slashes


class ScenarioError(ValueError):
    """Input that is not a valid scenario. `problems` are short, readable lines."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def check_scenario(sc: Scenario, slug: str, pack: VerticalPack, where: str = "") -> None:
    """The checks beyond the schema: tenant, category and action against the tenant's pack."""
    pre = f"{where}: " if where else ""
    if sc.tenant != slug:
        raise ValueError(f"{pre}tenant {sc.tenant!r} is not this folder's {slug!r}")
    if sc.expect.category is not None and sc.expect.category not in pack.issue_categories:
        raise ValueError(f"{pre}unknown category {sc.expect.category!r}")
    if sc.expect.action is not None and sc.expect.action not in pack.actions:
        raise ValueError(f"{pre}action {sc.expect.action!r} not in the pack")


def parse_scenario_text(text: str, slug: str, pack: VerticalPack) -> Scenario:
    """Untrusted YAML text -> a validated Scenario, or ScenarioError with readable problems.
    Safe load only; the same schema and pack checks as load_scenarios."""
    if len(text.encode("utf-8")) > MAX_SCENARIO_BYTES:
        raise ScenarioError([f"too large (limit {MAX_SCENARIO_BYTES} bytes)"])
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        at = f" at line {mark.line + 1}" if mark else ""
        raise ScenarioError([f"not valid YAML{at}"]) from None
    if not isinstance(data, dict):
        raise ScenarioError(["the file must be a mapping of fields (id, tenant, message, ...)"])
    try:
        sc = Scenario.model_validate(data)
    except ValidationError as exc:
        raise ScenarioError(
            [
                f"{'.'.join(str(x) for x in e['loc']) or 'scenario'}: {e['msg']}"
                for e in exc.errors()[:10]
            ]
        ) from None
    if not SCENARIO_ID.match(sc.id):
        raise ScenarioError(["id: use lowercase letters, digits and dashes only (max 63)"])
    try:
        check_scenario(sc, slug, pack)
    except ValueError as exc:
        raise ScenarioError([str(exc)]) from None
    return sc


def scenario_file(folder: Path, scenario_id: str) -> Path:
    """tenants/<slug>/scenarios/<id>.yaml for a safe id; never a path built from free text."""
    if not SCENARIO_ID.match(scenario_id):
        raise ScenarioError(["scenario id: lowercase letters, digits and dashes only"])
    base = (folder / "scenarios").resolve()
    path = (base / f"{scenario_id}.yaml").resolve()
    if path.parent != base:
        raise ScenarioError(["scenario id: not allowed"])
    return path


def load_scenarios(folder: Path, slug: str, pack: VerticalPack) -> list[Scenario]:
    """Every scenario of one tenant folder, checked against the tenant's vertical pack."""
    out: list[Scenario] = []
    for path in sorted((folder / "scenarios").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        sc = Scenario.model_validate(data)
        where = f"{path.name}"
        check_scenario(sc, slug, pack, where)
        if sc.id in {o.id for o in out}:
            raise ValueError(f"{where}: duplicate scenario id {sc.id!r}")
        out.append(sc)
    return out
