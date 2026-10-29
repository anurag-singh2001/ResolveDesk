"""Action interface + registry (PROJECT.md section 10).

Agents never call actions. They propose (action name + params); code validates the params
against `Input`, stores an immutable proposal, and the executor runs approved proposals only.
"""

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from app.core.tenancy import TenantContext


class Risk(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionInput(BaseModel):
    """Base for every action's params: unknown fields are an error, values are frozen, and
    amounts are strict ints (pydantic would otherwise coerce "349" or 349.0)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


@dataclass(frozen=True)
class Facts:
    """What eligibility may look at, read by the engine inside the tenant's transaction."""

    settings: dict[str, Any]  # effective settings for the order's brand + location
    order_total_paise: int | None = None
    refundable_paise: int | None = None  # captured payments minus held/succeeded refunds


@dataclass(frozen=True)
class AmountRange:
    """The amounts an approver may switch a case to for one action (S7.10). Advice for the
    screen only: `validate` stays the authority and re-checks every amount server-side."""

    min_paise: int
    max_paise: int
    step_paise: int = 1
    # Above this amount the action needs an hq_owner to approve (None: no such limit).
    hq_above_paise: int | None = None


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)  # shown to the approver


@dataclass(frozen=True)
class ExecutionResult:
    status: str  # submitted | processing | succeeded | failed | unknown
    provider_reference: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    status: str  # verified | mismatch | unknown
    detail: dict[str, Any] = field(default_factory=dict)


class Action(ABC):
    name: ClassVar[str]
    risk: ClassVar[Risk]
    Input: ClassVar[type[ActionInput]]
    # Whether params carry an amount the approval/limit rules must see.
    amount_field: ClassVar[str | None] = None
    # Whether an approval rule may approve it without a human (refunds: never).
    auto_approvable: ClassVar[bool] = False
    # Whether an approved proposal of this action counts as compensation granted to the
    # customer for the fair-use check (app/engine/eligibility.py, fair_use).
    counts_as_grant: ClassVar[bool] = False

    @abstractmethod
    def validate(self, ctx: TenantContext, inp: ActionInput, facts: "Facts") -> ValidationResult:
        """Deterministic eligibility from facts the engine read from the DB. No I/O here."""

    def can_auto_approve(self, inp: ActionInput, facts: "Facts") -> bool:
        return False

    def amount_range(self, facts: "Facts") -> AmountRange | None:
        """The amounts this action may be switched to for the order in `facts`, or None when it
        can't be offered as a switch (default). Pure: no I/O."""
        return None

    @abstractmethod
    def execute(
        self, ctx: TenantContext, inp: ActionInput, idempotency_key: str
    ) -> ExecutionResult: ...

    @abstractmethod
    def verify(self, ctx: TenantContext, result: ExecutionResult) -> VerificationResult: ...


_REGISTRY: dict[str, type[Action]] = {}


def register_action(cls: type[Action]) -> type[Action]:
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"action {cls.name!r} is already registered")
    if not issubclass(cls.Input, ActionInput):
        raise TypeError(f"{cls.name}.Input must subclass ActionInput")
    _REGISTRY[cls.name] = cls
    return cls


def get_action(name: str) -> type[Action]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown action {name!r}") from None


def registered_actions() -> dict[str, type[Action]]:
    return dict(_REGISTRY)


def enabled_actions(pack_actions: list[str]) -> dict[str, type[Action]]:
    """Actions a tenant may use: its vertical pack's list, all of which must be registered."""
    return {name: get_action(name) for name in pack_actions}
