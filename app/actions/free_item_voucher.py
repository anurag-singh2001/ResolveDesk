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
    auto_approvable = True
    counts_as_grant = True

    def validate(self, ctx, inp: VoucherInput, facts: Facts) -> ValidationResult:
        cap = facts.settings["voucher_max_paise"]
        errors = [] if inp.value_paise <= cap else ["voucher exceeds the voucher limit"]
        checks: dict = {"value_paise": inp.value_paise, "voucher_max_paise": cap}
        total = facts.order_total_paise
        if total is None:  # fail closed: a voucher always belongs to an order we can read
            errors.append("order total unknown, so the voucher cannot be checked")
        else:
            checks["order_total_paise"] = total  # shown next to the value to the approver
            if inp.value_paise > total:
                errors.append("voucher exceeds what the customer paid for the order")
        return ValidationResult(ok=not errors, errors=errors, checks=checks)

    def can_auto_approve(self, inp: VoucherInput, facts: Facts) -> bool:
        return inp.value_paise <= facts.settings["voucher_auto_approve_max_paise"]
