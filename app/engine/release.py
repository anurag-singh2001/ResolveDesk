"""Operator release of a quarantined refund (E4.4).

A refund the executor could not finish keeps its balance held: ledger `pending_reconciliation`
(quarantined after its approval lapsed), or `reserved` and never confirmed (the process died
around the send). Freeing that money is only safe once the provider can no longer apply an
earlier request with this key. The provider contract (PaymentConnector.request_lifetime)
bounds that, so release:

1. checks (DB only) that the row is still held, its approval can no longer be executed, and
   the window has passed: the later of the ledger's last change and the approval's expiry
   (after which no worker sends), plus the request lifetime, plus a margin;
2. asks the provider by key, outside any transaction;
3. records what the provider reports if it has the refund (money moved: never freed), or
   else marks the ledger `released` with a compare-and-set on the status seen in step 1, so
   a reconcile that recorded a late landing in between wins.

hq_owner only (enforced by the API), audited with the operator's user id.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.connectors.base import connector_for
from app.core import audit
from app.core.db import tenant_session
from app.core.models import ActionProposal, Approval, DomainEvent, Execution, RefundOperation
from app.core.tenancy import TenantContext
from app.engine import lifecycle
from app.engine.approvals import check_usable
from app.engine.eligibility import order_facts
from app.engine.executor import TERMINAL, _persist

RELEASABLE = ("pending_reconciliation", "reserved")
# Slack on top of the provider's request lifetime (clock skew, a worker slow to send).
RELEASE_MARGIN = timedelta(minutes=5)


@dataclass(frozen=True)
class ReleaseCheck:
    ok: bool
    reason: str | None = None  # not_found | not_held | still_executable | too_early
    ready_at: datetime | None = None
    ledger_status: str | None = None
    key: str | None = None
    settings: dict | None = None


@dataclass(frozen=True)
class ReleaseResult:
    outcome: str  # released | recorded | refused
    status: str | None = None  # ledger status afterwards
    reason: str | None = None


def check_release(session: Session, proposal_id: uuid.UUID, now: datetime) -> ReleaseCheck:
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None or proposal.action != "refund":
        return ReleaseCheck(False, "not_found")
    ledger = session.scalar(
        select(RefundOperation).where(RefundOperation.proposal_id == proposal_id)
    )
    if ledger is None:
        return ReleaseCheck(False, "not_held")  # nothing reserved: nothing to free
    if ledger.status not in RELEASABLE:
        return ReleaseCheck(False, "not_held", ledger_status=ledger.status)
    approval = session.scalar(select(Approval).where(Approval.proposal_id == proposal_id))
    if check_usable(approval, proposal, now).ok:
        # Still executable: a worker or the sweeper may send it right now. Let it finish.
        return ReleaseCheck(False, "still_executable", ledger_status=ledger.status)
    _, facts = order_facts(session, ledger.transaction_id)
    lifetime = connector_for(facts.settings, "payment").request_lifetime
    ready_at = max(ledger.updated_at, approval.expires_at) + lifetime + RELEASE_MARGIN
    if now < ready_at:
        return ReleaseCheck(False, "too_early", ready_at, ledger.status)
    return ReleaseCheck(True, None, ready_at, ledger.status, ledger.idempotency_key, facts.settings)


def release_refund(
    engine: Engine, ctx: TenantContext, proposal_id: uuid.UUID, now: datetime | None = None
) -> ReleaseResult:
    now = now or datetime.now(UTC)
    with tenant_session(ctx.tenant_id, engine) as s:
        check = check_release(s, proposal_id, now)
    if not check.ok:
        return ReleaseResult("refused", check.ledger_status, check.reason)
    # No transaction is open during the provider lookup (hard rule 5).
    found = connector_for(check.settings, "payment").find_refund(ctx, check.key)
    if found is not None and found.status == "unavailable":
        return ReleaseResult("refused", check.ledger_status, "provider_unavailable")
    if found is not None:  # the provider has it: the money moved (or may): record, never free
        _persist(engine, ctx, proposal_id, check.key, found)
        with tenant_session(ctx.tenant_id, engine) as s:
            _audit(s, ctx, proposal_id, "refund.release_refused_provider_has_it",
                   {"provider_status": found.status})  # fmt: skip
            status = _ledger_status(s, proposal_id)
        return ReleaseResult("recorded", status, "provider_has_record")
    with tenant_session(ctx.tenant_id, engine) as s:
        changed = s.execute(
            update(RefundOperation)
            .where(
                RefundOperation.proposal_id == proposal_id,
                RefundOperation.status == check.ledger_status,  # compare-and-set
            )
            .values(status="released")
        ).rowcount
        if not changed:  # something (e.g. a late landing) was recorded meanwhile
            return ReleaseResult("refused", _ledger_status(s, proposal_id), "changed")
        s.execute(
            update(Execution)
            .where(Execution.proposal_id == proposal_id, Execution.status.notin_(TERMINAL))
            .values(
                status="failed",
                error="released by operator: provider has no record",
                never_sent=True,
            )
        )
        _audit(s, ctx, proposal_id, "refund.released",
               {"previous_status": check.ledger_status,
                "ready_at": check.ready_at.isoformat()})  # fmt: skip
        s.add(
            DomainEvent(
                tenant_id=ctx.tenant_id,
                event="refund.released",
                entity_id=proposal_id,
                payload={"idempotency_key": check.key},
            )
        )
        case_id = s.get(ActionProposal, proposal_id).case_id
    # The refund will not happen: a person owns the case (never overwrites a closed one).
    lifecycle.escalate(
        engine, ctx.tenant_id, case_id, "refund released by operator: provider has no record"
    )
    return ReleaseResult("released", "released")


def _ledger_status(session: Session, proposal_id: uuid.UUID) -> str | None:
    return session.scalar(
        select(RefundOperation.status).where(RefundOperation.proposal_id == proposal_id)
    )


def _audit(session, ctx, proposal_id, event, payload) -> None:
    audit.record(
        session,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event=event,
        entity_type="proposal",
        entity_id=proposal_id,
        payload=payload,
    )
