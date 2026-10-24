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
from app.core.money import percent_of


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

    def validate(self, ctx, inp: RefundInput, facts: Facts) -> ValidationResult:
        s = facts.settings
        errors = []
        cap = percent_of(facts.order_total_paise, s["refund_max_percent"])
        if s["refund_channel"] != "tenant_gateway":
            errors.append("refunds for this order go through the aggregator, not us")
        if inp.amount_paise > cap:
            errors.append(f"amount exceeds {s['refund_max_percent']}% of the order")
        if inp.amount_paise > facts.refundable_paise:
            errors.append("amount exceeds the refundable balance")
        return ValidationResult(
            ok=not errors,
            errors=errors,
            checks={
                "amount_paise": inp.amount_paise,
                "order_total_paise": facts.order_total_paise,
                "max_by_percent_paise": cap,
                "refundable_paise": facts.refundable_paise,
                "needs_hq": inp.amount_paise > s["refund_without_escalation_paise"],
            },
        )
