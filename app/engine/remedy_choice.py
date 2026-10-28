"""Customer's choice between the remedies a category's rule allows (S7.9).

Everything shown or stored here comes from code: the options are the pack rule's, the amounts
are computed by the resolver (voucher sized per S7.8; refund within the percent cap and the
refundable balance), and "usually instant" vs "after a team member approves" is derived from
the action's own auto-approve rule and settings. A customer's pick is only an option code; the
proposal is built from the rule, so a pick can never widen an amount.
"""

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.base import get_action
from app.core import audit
from app.core.i18n import normalize, t
from app.core.models import ActionProposal, Case, Customer, Transaction
from app.core.money import format_inr
from app.core.tenancy import TenantContext
from app.engine.eligibility import order_facts
from app.engine.resolver import ChoiceOption, remedy_options

CHOOSABLE_STATUSES = ("investigating", "awaiting_info")


class InvalidChoice(ValueError):
    """The pick is not one of the options the rule allows for this order and category."""


class ChoiceClosed(ValueError):
    """The case is already decided (or not the kind that takes a choice)."""


def _approval(option: ChoiceOption, facts) -> str:
    action_cls = get_action(option.remedy.action)
    if not action_cls.auto_approvable:
        return "team"
    inp = action_cls.Input.model_validate_json(json.dumps(option.remedy.params))
    return "instant" if action_cls().can_auto_approve(inp, facts) else "team"


def _view(option: ChoiceOption, facts, language: str) -> dict:
    remedy = option.remedy
    kind = "refund" if remedy.action == "refund" else "voucher"
    amount = remedy.params.get("amount_paise", remedy.params.get("value_paise"))
    approval = _approval(option, facts)
    return {
        "code": option.code,
        "kind": kind,
        "title": t(f"option.{kind}.title", language),
        "summary": t(f"option.{kind}.summary", language, amount=format_inr(amount)),
        "amount_paise": amount,
        "approval": approval,
        "timing": t(f"option.timing.{approval}", language),
    }


def options_for_order(
    session: Session, order: Transaction, category: str, language: object
) -> list[dict]:
    """The options to show for this order and category; [] or one entry means no choice."""
    lang = normalize(language)
    _, facts = order_facts(session, order.id)
    return [_view(o, facts, lang) for o in remedy_options(session, order, facts, category)]


def customer_language(session: Session, ctx: TenantContext) -> str:
    return normalize(
        session.scalar(select(Customer.preferred_language).where(Customer.user_id == ctx.user_id))
    )


def check_choice(session: Session, order: Transaction, category: str | None, code: str) -> None:
    """Raise InvalidChoice unless `code` is a currently offered option for this order/category."""
    if category is None:
        raise InvalidChoice("choose a category first")
    _, facts = order_facts(session, order.id)
    if code not in {o.code for o in remedy_options(session, order, facts, category)}:
        raise InvalidChoice("that option is not available for this order")


def record_choice(session: Session, ctx: TenantContext, case: Case, code: str) -> None:
    case.remedy_choice = code
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="case.remedy_choice",
        entity_type="case",
        entity_id=case.id,
        payload={"option": code},  # the option code only, never free text
    )


def set_choice(session: Session, ctx: TenantContext, case_id: uuid.UUID, code: str) -> Case:
    """Change the pick on the caller's own undecided case (the caller checked ownership)."""
    case = session.scalar(select(Case).where(Case.id == case_id).with_for_update())
    if case is None or case.transaction_id is None:
        raise ChoiceClosed("this case takes no choice")
    has_proposal = session.scalar(
        select(ActionProposal.id).where(ActionProposal.case_id == case.id).limit(1)
    )
    if case.status not in CHOOSABLE_STATUSES or has_proposal is not None:
        raise ChoiceClosed("this case has already been decided")
    order = session.get(Transaction, case.transaction_id)
    check_choice(session, order, case.category, code)
    record_choice(session, ctx, case, code)
    return case
