import uuid

from pydantic import Field

from app.actions._pending import NotYetExecutable
from app.actions.base import Action, ActionInput, Risk, register_action


class RefundInput(ActionInput):
    transaction_id: uuid.UUID
    amount_paise: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


@register_action
class Refund(NotYetExecutable, Action):
    """Money back to the original payment. Always human-approved (PROJECT.md section 2)."""

    name = "refund"
    risk = Risk.HIGH
    Input = RefundInput
    amount_field = "amount_paise"
