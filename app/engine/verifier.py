"""Verify step (PROJECT.md section 8, step 7): re-read the provider by idempotency key and
compare with what we recorded. A case reaches confirmed/resolved only when the provider's own
record matches ours (status, amount, reference); a mismatch escalates to a person.

Three short steps: read our execution (transaction), ask the provider (no transaction open,
hard rule 5), record the verification and move the case (transaction). Once a final verdict
(verified or mismatch) exists, verifying again returns it without calling the provider.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.connectors.base import RefundOutcome, connector_for
from app.core import audit, events
from app.core.db import tenant_session
from app.core.models import ActionProposal, Case, Execution, Verification
from app.core.tenancy import TenantContext
from app.engine.eligibility import order_facts

FINAL = ("verified", "mismatch")
# Error prefixes of failed executions that never reached the provider (executor refusal,
# operator release).
NEVER_SENT = ("refused:", "released by operator")


@dataclass(frozen=True)
class VerifyResult:
    status: str  # verified | mismatch | unknown | pending (execution not finished yet)
    execution_status: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class _Snapshot:
    execution_id: uuid.UUID
    case_id: uuid.UUID
    key: str
    status: str
    reference: str | None
    amount_paise: int
    settings: dict
    never_sent: bool = False


def verify_refund(engine, ctx: TenantContext, proposal_id: uuid.UUID) -> VerifyResult:
    snap = _snapshot(engine, ctx, proposal_id)
    if isinstance(snap, VerifyResult):
        return snap
    found = connector_for(snap.settings, "payment").find_refund(ctx, snap.key)  # no tx open
    status, detail = compare(
        snap.status, snap.reference, snap.amount_paise, found, never_sent=snap.never_sent
    )
    with tenant_session(ctx.tenant_id, engine) as s:
        # Serialize overlapping passes (decision task, reconcile, graph resume) on the
        # execution row, then re-check: only the first records a final verdict.
        s.scalar(select(Execution.id).where(Execution.id == snap.execution_id).with_for_update())
        earlier = s.scalars(
            select(Verification)
            .where(Verification.execution_id == snap.execution_id)
            .where(Verification.status.in_(FINAL))
            .order_by(Verification.created_at.desc(), Verification.id)
        ).first()
        if earlier is not None:
            return VerifyResult(earlier.status, snap.status, earlier.detail.get("reason", ""))
        s.add(
            Verification(
                tenant_id=ctx.tenant_id,
                execution_id=snap.execution_id,
                status=status,
                detail={
                    "reason": detail,
                    "provider_status": found.status if found else None,
                    "execution_status": snap.status,
                },
            )
        )
        audit.record(
            s,
            ctx.tenant_id,
            actor_type="system",
            actor_id=None,
            event=f"verification.{status}",
            entity_type="proposal",
            entity_id=proposal_id,
            payload={"reason": detail, "execution_status": snap.status},
        )
        case = s.get(Case, snap.case_id)
        if case.status != "executing":
            pass  # a person (or another path) already closed or escalated it: never overwrite
        elif status == "verified" and snap.status == "succeeded":
            case.status = "resolved"
            events.emit(s, ctx.tenant_id, "case.verified", case.id,
                        {"proposal_id": str(proposal_id), "status": status})  # fmt: skip
        elif status != "unknown":  # mismatch, or the provider confirms the refund failed
            case.status = "escalated"
            events.emit(s, ctx.tenant_id, "case.escalated", case.id,
                        {"proposal_id": str(proposal_id), "reason": detail})  # fmt: skip
    return VerifyResult(status, snap.status, detail)


def compare(
    execution_status: str,
    reference: str | None,
    amount_paise: int,
    found: RefundOutcome | None,
    never_sent: bool = False,
) -> tuple[str, str]:
    """(verified | mismatch | unknown, why). The provider is the source of truth.
    `never_sent`: a failed execution recorded without any provider call (refused before
    sending, or released by an operator after the provider's request lifetime): no provider
    record is the expected, final state - not "unknown" forever."""
    if found is None:
        if never_sent and execution_status == "failed":
            return "verified", "never sent: provider has no record, as expected"
        if execution_status == "succeeded":
            return "mismatch", "provider has no record of this refund"
        return "unknown", "provider has no record yet"
    if found.status == "unavailable":
        return "unknown", "provider unavailable"
    if found.status != execution_status:
        return "mismatch", f"provider says {found.status}, we recorded {execution_status}"
    if execution_status == "failed":
        return "verified", "provider confirms the refund failed"
    if found.amount_paise is None:
        return "unknown", "provider did not report the amount"
    if found.amount_paise != amount_paise:
        return "mismatch", "provider amount differs from the approved amount"
    if reference and found.provider_reference and found.provider_reference != reference:
        return "mismatch", "provider reference differs from ours"
    return "verified", "provider confirms the refund"


def _snapshot(engine, ctx, proposal_id) -> "_Snapshot | VerifyResult":
    with tenant_session(ctx.tenant_id, engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        execution = s.scalar(select(Execution).where(Execution.proposal_id == proposal_id))
        if proposal is None or execution is None:
            return VerifyResult("pending", None, "not executed")
        latest = s.scalars(
            select(Verification)
            .where(Verification.execution_id == execution.id)
            .order_by(Verification.created_at.desc(), Verification.id)
        ).first()
        if latest is not None and latest.status in FINAL:
            return VerifyResult(latest.status, execution.status, latest.detail.get("reason", ""))
        if execution.status not in ("succeeded", "failed"):
            return VerifyResult("pending", execution.status, "execution not finished")
        return _Snapshot(
            execution.id,
            proposal.case_id,
            execution.idempotency_key,
            execution.status,
            execution.provider_reference,
            proposal.params["amount_paise"],  # the hashed, approved params
            # The same (brand/location-narrowed) settings the executor used to pick the connector.
            order_facts(s, uuid.UUID(proposal.params["transaction_id"]))[1].settings,
            (execution.error or "").startswith(NEVER_SENT),
        )
