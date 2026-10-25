"""Scenario files: tenants/<slug>/scenarios/*.yaml, one scenario per file (PROJECT.md 13).

A scenario names an order *selector* (e.g. the most late delivery, an order with a missing
item), never a hard-coded id, so it survives a reseed. `expect` is the outcome the tenant's
own rules call for; scoring is deterministic code (evals/metrics.py).
"""

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    message: str = Field(min_length=1)
    order: OrderSelector
    expect: Expect
    held_out: bool = False
    tags: list[str] = Field(default_factory=list)  # e.g. "live": also in pytest -m live
    note: str = ""


def load_scenarios(folder: Path, slug: str, pack: VerticalPack) -> list[Scenario]:
    """Every scenario of one tenant folder, checked against the tenant's vertical pack."""
    out: list[Scenario] = []
    for path in sorted((folder / "scenarios").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        sc = Scenario.model_validate(data)
        where = f"{path.name}"
        if sc.tenant != slug:
            raise ValueError(f"{where}: tenant {sc.tenant!r} is not this folder's {slug!r}")
        if sc.expect.category is not None and sc.expect.category not in pack.issue_categories:
            raise ValueError(f"{where}: unknown category {sc.expect.category!r}")
        if sc.expect.action is not None and sc.expect.action not in pack.actions:
            raise ValueError(f"{where}: action {sc.expect.action!r} not in the pack")
        if sc.id in {o.id for o in out}:
            raise ValueError(f"{where}: duplicate scenario id {sc.id!r}")
        out.append(sc)
    return out
