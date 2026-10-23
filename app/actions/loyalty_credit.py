import uuid

from pydantic import Field

from app.actions._pending import NotYetExecutable
from app.actions.base import Action, ActionInput, Risk, register_action


class LoyaltyCreditInput(ActionInput):
    customer_id: uuid.UUID
    points: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


@register_action
class LoyaltyCredit(NotYetExecutable, Action):
    name = "loyalty_credit"
    risk = Risk.MEDIUM
    Input = LoyaltyCreditInput
