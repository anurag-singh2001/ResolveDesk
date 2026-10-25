"""Crash recovery (E4.5). Finishes work an in-process background task never did.

1. Approved, unexpired proposals with no execution (the process died between committing the
   decision and running the task): run them with the same executor and the same stable key.
2. Executions left unfinished (`submitted`, `unknown`, `processing`): reconcile by key. This
   is also how a quarantined refund's late landing gets recorded.
3. Cases stuck in `investigating` past the agent run TTL (the run died, or never started):
   mark the dead run failed and escalate the case to a person. Escalating, not re-running:
   a maintenance job should not spend LLM budget, and a person sees the case at once.

Running it twice, or while a background task runs the same proposal, writes nothing twice:
the executors serialise on the proposal and resume by key.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select, update

from app.core import audit
from app.core.db import tenant_session
from app.core.models import ActionProposal, Approval, Case, Execution, WorkflowRun
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine.dispatch import EXECUTORS, reconcile, run_approved
from app.engine.executor import TERMINAL
from app.engine.graph import RUN_TTL

log = logging.getLogger(__name__)

# Leave fresh work to the background task that is (probably) still running it.
MIN_AGE = timedelta(minutes=1)


@dataclass
class SweepReport:
    executed: list[str] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    escalated_cases: list[str] = field(default_factory=list)


def sweep_tenant(
    engine: Engine,
    tenant_id: uuid.UUID,
    now: datetime | None = None,
    min_age: timedelta = MIN_AGE,
    run_ttl: timedelta = RUN_TTL,
) -> SweepReport:
    now = now or datetime.now(UTC)
    report = SweepReport()
    with tenant_session(tenant_id, engine) as s:
        never_run = s.execute(
            select(ActionProposal.id, ActionProposal.action)
            .join(Approval, Approval.proposal_id == ActionProposal.id)
            .outerjoin(Execution, Execution.proposal_id == ActionProposal.id)
            .where(
                Approval.decision == "approved",
                Approval.expires_at > now,
                Approval.decided_at <= now - min_age,
                Execution.id.is_(None),
                ActionProposal.action.in_(list(EXECUTORS)),
            )
            .order_by(Approval.decided_at)
        ).all()
        unfinished = s.execute(
            select(ActionProposal.id, ActionProposal.action)
            .join(Execution, Execution.proposal_id == ActionProposal.id)
            .where(
                Execution.status.notin_(TERMINAL),
                Execution.updated_at <= now - min_age,
                ActionProposal.action.in_(list(EXECUTORS)),
            )
            .order_by(Execution.updated_at)
        ).all()
    # Provider calls happen here, with no transaction open (hard rule 5).
    for proposal_id, action in never_run:
        run_approved(engine, tenant_id, proposal_id, action)
        report.executed.append(str(proposal_id))
    for proposal_id, action in unfinished:
        reconcile(engine, tenant_id, proposal_id, action)
        report.reconciled.append(str(proposal_id))
    report.escalated_cases = _escalate_stuck_cases(engine, tenant_id, now, run_ttl)
    return report


def _escalate_stuck_cases(engine, tenant_id, now, run_ttl) -> list[str]:
    cutoff = now - run_ttl
    escalated = []
    with tenant_session(tenant_id, engine) as s:
        # SKIP LOCKED: a run claiming a case right now holds its row; leave that one alone.
        cases = s.scalars(
            select(Case)
            .where(Case.status == "investigating", Case.updated_at < cutoff)
            .with_for_update(skip_locked=True)
        ).all()
        for case in cases:
            running = (WorkflowRun.case_id == case.id) & (WorkflowRun.status == "running")
            live = s.scalar(select(WorkflowRun.id).where(running, WorkflowRun.created_at >= cutoff))
            if live is not None:
                continue
            s.execute(
                update(WorkflowRun)
                .where(running)
                .values(status="failed", error="abandoned: no result within the run TTL")
            )
            case.status = "escalated"
            audit.record(
                s,
                tenant_id,
                actor_type="system",
                actor_id=None,
                event="case.escalated",
                entity_type="case",
                entity_id=case.id,
                payload={"reason": "agent run did not finish within the run TTL"},
            )
            escalated.append(str(case.id))
    return escalated


def sweep_all(engine: Engine, now: datetime | None = None) -> dict[str, SweepReport]:
    """Every tenant folder, each in its own RLS scope. One tenant's failure doesn't stop the
    others."""
    reports = {}
    for folder in tenant_dirs():
        slug = load_tenant(folder).slug
        try:
            reports[slug] = sweep_tenant(engine, tenant_id_for(slug), now)
        except Exception:
            log.exception("sweep failed for tenant %s", slug)
    return reports
