import uuid

from pydantic import Field

from app.actions._pending import NotYetExecutable
from app.actions.base import (
    Action,
    ActionInput,
    Facts,
    Risk,
    ValidationResult,
    register_action,
)


class LoyaltyCreditInput(ActionInput):
    customer_id: uuid.UUID
    points: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


@register_action
class LoyaltyCredit(NotYetExecutable, Action):
    name = "loyalty_credit"
    risk = Risk.MEDIUM
    Input = LoyaltyCreditInput

    def validate(self, ctx, inp: LoyaltyCreditInput, facts: Facts) -> ValidationResult:
        cap = facts.settings.get("loyalty_credit_max_points", 0)
        errors = [] if inp.points <= cap else ["points exceed the loyalty credit limit"]
        return ValidationResult(ok=not errors, errors=errors, checks={"points": inp.points})
