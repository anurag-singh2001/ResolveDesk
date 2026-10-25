"""Crash recovery (E4.5). Finishes work an in-process background task never did.

1. Approved, unexpired proposals with no execution (the process died between committing the
   decision and running the task): run them with the same executor and the same stable key.
2. Executions left unfinished (`submitted`, `unknown`, `processing`): reconcile by key. This
   is also how a quarantined refund's late landing gets recorded.
3. Refunds the provider answered for but nobody verified (the process died between the
   executor and the verify step): run the verifier, so the case is not left on "processing".
4. Cases stuck in `investigating` past the agent run TTL (the run died, or never started):
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

from app.core import audit, events
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Execution,
    Verification,
    WorkflowRun,
)
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine.agent_runner import resume_after_decision
from app.engine.dispatch import EXECUTORS, reconcile, run_approved
from app.engine.executor import TERMINAL
from app.engine.graph import RUN_TTL, prune_finished
from app.engine.lifecycle import verify_executed
from app.engine.verifier import FINAL

log = logging.getLogger(__name__)

# Leave fresh work to the background task that is (probably) still running it.
MIN_AGE = timedelta(minutes=1)


@dataclass
class SweepReport:
    executed: list[str] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    escalated_cases: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    pruned_threads: int = 0
    events_published: int = 0


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
            select(ActionProposal.id, ActionProposal.action, ActionProposal.case_id)
            .join(Approval, Approval.proposal_id == ActionProposal.id)
            .join(Case, Case.id == ActionProposal.case_id)
            .outerjoin(Execution, Execution.proposal_id == ActionProposal.id)
            .where(
                Approval.decision == "approved",
                # Usable approvals run; a lapsed one is refused (and escalated) once, while
                # its case is still open - then it is no longer selected.
                (Approval.expires_at > now) | Case.status.in_(("executing", "awaiting_approval")),
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
        # A refund the provider answered for, but whose process died before the verify step:
        # the customer would stay on "processing" for money that moved. Verify it (refunds
        # only: vouchers have no verdict row, see lifecycle.verify_executed).
        final = select(Verification.id).where(
            Verification.execution_id == Execution.id, Verification.status.in_(FINAL)
        )
        unverified = s.scalars(
            select(ActionProposal.id)
            .join(Execution, Execution.proposal_id == ActionProposal.id)
            .where(
                ActionProposal.action == "refund",
                Execution.status.in_(("succeeded", "failed")),
                Execution.updated_at <= now - min_age,
                ~final.exists(),
            )
            .order_by(Execution.updated_at)
        ).all()
    # Provider calls happen here, with no transaction open (hard rule 5).
    # Each item is isolated: one bad proposal must not skip the rest of the sweep.
    for proposal_id, action, case_id in never_run:
        # A paused graph thread for this case resumes (its execute node is the same single
        # path); with none claimable, run the path directly. Either way: one stable key.
        # An approval that lapsed unexecuted is refused there and escalates the case.
        try:
            if _resume(engine, tenant_id, case_id, proposal_id).get("outcome") == "skipped":
                run_approved(engine, tenant_id, proposal_id, action)
        except Exception:
            log.exception("sweeper: could not execute proposal %s", proposal_id)
        report.executed.append(str(proposal_id))
    for proposal_id, action in unfinished:
        try:
            reconcile(engine, tenant_id, proposal_id, action)
        except Exception:
            log.exception("sweeper: could not reconcile proposal %s", proposal_id)
        report.reconciled.append(str(proposal_id))
    for proposal_id in unverified:
        try:
            verify_executed(engine, tenant_id, proposal_id)
        except Exception:
            log.exception("sweeper: could not verify proposal %s", proposal_id)
        report.verified.append(str(proposal_id))
    try:
        report.escalated_cases = _escalate_stuck_cases(engine, tenant_id, now, run_ttl)
    except Exception:
        log.exception("could not escalate stuck cases for tenant %s", tenant_id)
    # Housekeeping, each best effort: one failing must not stop the other or hide the work
    # above. Finished runs' checkpoints go; customer updates whose subscriber failed retry.
    try:
        _complete_decided_runs(engine, tenant_id)
    except Exception:
        log.exception("could not complete decided runs for tenant %s", tenant_id)
    try:
        report.pruned_threads = prune_finished(engine, tenant_id)
    except Exception:
        log.exception("could not prune checkpoints for tenant %s", tenant_id)
    try:
        report.events_published = events.publish_pending(engine, tenant_id)
    except Exception:
        log.exception("could not publish pending events for tenant %s", tenant_id)
    return report


def _complete_decided_runs(engine, tenant_id) -> int:
    """A run left 'paused' at approve whose proposal was decided and finished without the
    graph (the sweeper or a fallback ran it): nothing will ever resume it, so mark it
    completed. Then prune_finished may delete its checkpoint thread."""
    finished = (
        select(ActionProposal.id)
        .outerjoin(Approval, Approval.proposal_id == ActionProposal.id)
        .outerjoin(Execution, Execution.proposal_id == ActionProposal.id)
        .where(
            ActionProposal.case_id == WorkflowRun.case_id,
            (Approval.decision == "rejected") | Execution.status.in_(TERMINAL),
        )
    )
    with tenant_session(tenant_id, engine) as s:
        waiting = select(Case.id).where(Case.status.in_(("awaiting_info", "awaiting_approval")))
        return s.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.status == "paused",
                WorkflowRun.case_id.not_in(waiting),
                finished.exists(),
            )
            .values(status="completed")
        ).rowcount


def _resume(engine, tenant_id, case_id, proposal_id) -> dict:
    try:
        return resume_after_decision(engine, tenant_id, case_id, proposal_id)
    except Exception:
        log.exception("could not resume the workflow of case %s", case_id)
        return {"outcome": "skipped"}


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
