import uuid

from pydantic import Field

from app.actions._pending import NotYetExecutable
from app.actions.base import Action, ActionInput, Risk, register_action


class VoucherInput(ActionInput):
    transaction_id: uuid.UUID
    value_paise: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


@register_action
class FreeItemVoucher(NotYetExecutable, Action):
    """A voucher for a future order. May be auto-approved up to a tenant setting."""

    name = "free_item_voucher"
    risk = Risk.MEDIUM
    Input = VoucherInput
    amount_field = "value_paise"
