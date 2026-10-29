"""Immutable action proposals bound to a payload hash (PROJECT.md sections 7, 8).

A proposal is what an approver approves. Its hash covers everything material (action, case,
params), so an approval can never be replayed against different money, a different order or
a different action. Params come from an agent or a human form; they are validated here, in
code, before anything is stored.
"""

import hashlib
import json
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.actions  # noqa: F401  (registers the built-in actions)
from app.actions.base import enabled_actions
from app.core.models import ActionProposal, Case, Transaction
from app.core.settings_resolver import tenant_pack


class ProposalError(ValueError):
    """Params are invalid or the action isn't enabled for this tenant."""


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 kept. Floats are refused, so the
    hash can't depend on how a number was formatted (money is integer paise anyway)."""

    def check(v: Any) -> None:
        if isinstance(v, float):
            raise ProposalError("floats are not allowed in proposal payloads")
        if isinstance(v, dict):
            for k, item in v.items():
                if not isinstance(k, str):
                    raise ProposalError("payload keys must be strings")
                check(item)
        elif isinstance(v, list | tuple):
            for item in v:
                check(item)

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(action: str, case_id: uuid.UUID, params: dict[str, Any]) -> str:
    material = {"action": action, "case_id": str(case_id), "params": params}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def parse_params(action_cls, params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the action's strict Input in JSON mode (so uuid strings parse, but
    "34900" or 349.0 for an int amount is still rejected), then normalise for hashing."""
    try:
        parsed = action_cls.Input.model_validate_json(json.dumps(params))
    except (ValidationError, TypeError, ValueError) as exc:
        raise ProposalError(f"invalid params for {action_cls.name}: {exc}") from exc
    return parsed.model_dump(mode="json")


def create_proposal(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    case_id: uuid.UUID,
    action: str,
    params: dict[str, Any],
    reason: str,
    citations: list[dict] | None = None,
    run_id: uuid.UUID | None = None,
    basis: list[dict] | None = None,
) -> ActionProposal:
    """Store an immutable proposal in the caller's tenant (session must be scoped to it)."""
    enabled = enabled_actions(tenant_pack(session).actions)
    if action not in enabled:
        raise ProposalError(f"action {action!r} is not enabled for this tenant")
    action_cls = enabled[action]
    normalised = parse_params(action_cls, params)
    _check_case_binding(session, case_id, normalised)
    amount = normalised.get(action_cls.amount_field) if action_cls.amount_field else None
    proposal = ActionProposal(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        case_id=case_id,
        run_id=run_id,
        action=action,
        params=normalised,
        payload_hash=payload_hash(action, case_id, normalised),
        amount_paise=amount,
        amount_param=action_cls.amount_field if amount is not None else None,
        risk=action_cls.risk.value,
        reason=reason,
        citations=citations or [],
        # Which rule set the amount: structured codes from code, never model text (S8.3).
        validation={"basis": basis} if basis else {},
    )
    session.add(proposal)
    session.flush()
    return proposal


def _check_case_binding(session: Session, case_id: uuid.UUID, params: dict[str, Any]) -> None:
    """Ids inside params (from a model or a customer) must belong to this case (hard rule 8):
    the case's own order, or an order of the case's customer; the case's customer; the case."""
    case = session.get(Case, case_id)  # RLS: another tenant's case is simply not found
    if case is None:
        raise ProposalError("unknown case")
    if "case_id" in params and uuid.UUID(params["case_id"]) != case.id:
        raise ProposalError("params.case_id is not this case")
    if "customer_id" in params and uuid.UUID(params["customer_id"]) != case.customer_id:
        raise ProposalError("params.customer_id is not this case's customer")
    if "transaction_id" in params:
        order_id = uuid.UUID(params["transaction_id"])
        if case.transaction_id is not None and order_id != case.transaction_id:
            raise ProposalError("params.transaction_id is not this case's order")
        owner = session.scalar(select(Transaction.customer_id).where(Transaction.id == order_id))
        if owner != case.customer_id:
            raise ProposalError("params.transaction_id is not an order of this customer")


def proposal_hash_is_intact(proposal: ActionProposal) -> bool:
    """Recompute from stored fields (the executor calls this before acting)."""
    return proposal.payload_hash == payload_hash(proposal.action, proposal.case_id, proposal.params)
