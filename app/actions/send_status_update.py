import uuid
from typing import Literal

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


class StatusUpdateInput(ActionInput):
    case_id: uuid.UUID
    # Only states a tool confirmed may be stated to the customer (hard rule 7).
    state: Literal["received", "investigating", "awaiting_approval", "confirmed", "declined"]
    message: str = Field(min_length=1, max_length=1000)


@register_action
class SendStatusUpdate(NotYetExecutable, Action):
    name = "send_status_update"
    risk = Risk.LOW
    Input = StatusUpdateInput
    auto_approvable = True

    def validate(self, ctx, inp: StatusUpdateInput, facts: Facts) -> ValidationResult:
        return ValidationResult(ok=True)

    def can_auto_approve(self, inp: StatusUpdateInput, facts: Facts) -> bool:
        return True
