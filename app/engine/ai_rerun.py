"""Re-run the AI on a case that escalated because the AI was unavailable (S7.4).

The agent path is reused as is: this module only puts the case back to `investigating`
(under the case row lock, so a double click or a concurrent sweeper starts exactly one run)
and calls the same `run_agents` a new case uses. Agents stay read-only and the executor still
writes only approved proposals; nothing here writes a proposal, reply or payout.

Eligible = the case is `escalated` and its latest `case.escalated` audit reason is an AI
failure ("AI unavailable: <error>", or "LLM: <error>" for a provider error). Any other
escalation (a person's decision, a policy limit) is not.

The sweeper retries automatically, bounded: at most MAX_AUTO_ATTEMPTS system attempts per
case, spaced by an exponential backoff from the latest escalation. Staff presses are not
counted (a person decides). Audit: `case.ai_rerun_requested` and `case.ai_rerun_result`
carry codes only, never message text.
"""

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select

from app.core import audit
from app.core.db import tenant_session
from app.core.models import AuditEvent, Case
from app.engine import agent_runner
from app.engine.case_messages import customer_messages

log = logging.getLogger(__name__)

MAX_AUTO_ATTEMPTS = 3
BACKOFF_BASE = timedelta(minutes=5)  # 5, 10, 20 minutes after the latest escalation
MAX_MESSAGE = 4000  # same cap the graph uses when it re-reads the customer's words
# "LLM: <class>" reasons a retry can fix; budget/format errors would repeat, so they stay put.
_TRANSIENT = {"ProviderFailed", "MissingAPIKey", "RateLimited"}
_REASON = re.compile(r"^(AI unavailable|LLM): (\w+)$")

STARTED, ALREADY_RUNNING, NOT_ELIGIBLE = "started", "already_running", "not_eligible"


@dataclass(frozen=True)
class RerunState:
    error: str  # the exception class name recorded in the escalation reason
    escalated_at: datetime
    auto_attempts: int
    requested_after_escalation: bool


def is_ai_failure(reason: str | None) -> bool:
    m = _REASON.match(reason or "")
    return bool(m) and (m.group(1) == "AI unavailable" or m.group(2) in _TRANSIENT)


def rerun_state(s, case: Case) -> RerunState | None:
    """The case's AI-failure escalation, or None when it did not escalate for one. Status is
    not checked here: an `investigating` case right after a request still has the old
    escalation as its latest."""
    events = list(
        s.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.entity_id == case.id,
                AuditEvent.event.in_(("case.escalated", "case.ai_rerun_requested")),
            )
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        )
    )
    escalations = [e for e in events if e.event == "case.escalated"]
    if not escalations or not is_ai_failure(escalations[-1].payload.get("reason")):
        return None
    last = escalations[-1]
    requests = [e for e in events if e.event == "case.ai_rerun_requested"]
    return RerunState(
        error=_REASON.match(last.payload["reason"]).group(2),
        escalated_at=last.occurred_at,
        auto_attempts=sum(1 for e in requests if e.payload.get("trigger") == "sweeper"),
        requested_after_escalation=bool(requests) and requests[-1].occurred_at >= last.occurred_at,
    )


def can_rerun(s, case: Case) -> bool:
    return case.status == "escalated" and rerun_state(s, case) is not None


def request_rerun(
    engine: Engine,
    tenant_id: uuid.UUID,
    case_id: uuid.UUID,
    *,
    trigger: str,
    actor_id: uuid.UUID | None = None,
) -> str:
    """Claim the re-run: escalated -> investigating under the case row lock, audited. Returns
    STARTED (the caller now runs it), ALREADY_RUNNING (someone just claimed it) or
    NOT_ELIGIBLE. `case_id` must come from a case already loaded under the caller's scope."""
    with tenant_session(tenant_id, engine) as s:
        case = s.scalar(select(Case).where(Case.id == case_id).with_for_update())
        if case is None:
            return NOT_ELIGIBLE
        state = rerun_state(s, case)
        if state is None:
            return NOT_ELIGIBLE
        if case.status == "investigating" and state.requested_after_escalation:
            return ALREADY_RUNNING
        if case.status != "escalated":
            return NOT_ELIGIBLE
        case.status = "investigating"
        audit.record(
            s,
            tenant_id,
            actor_type="user" if actor_id else "system",
            actor_id=actor_id,
            event="case.ai_rerun_requested",
            entity_type="case",
            entity_id=case.id,
            payload={"trigger": trigger, "previous_error": state.error},
        )
        return STARTED


def run_requested(engine: Engine, tenant_id: uuid.UUID, case_id: uuid.UUID, trigger: str) -> dict:
    """Background task after request_rerun returned STARTED (no transaction is open while the
    models are called). Reads the customer's words from the ticket, runs the normal agent
    path, audits the outcome (a code, not text)."""
    outcome = "error"
    try:
        with tenant_session(tenant_id, engine) as s:
            message = "\n".join(b for _, b in customer_messages(s, case_id))[-MAX_MESSAGE:]
        out = agent_runner.run_agents(engine, tenant_id, case_id, message)
        outcome = out.get("outcome") or "unknown"
    except Exception:
        log.exception("AI re-run of case %s failed", case_id)
    try:
        with tenant_session(tenant_id, engine) as s:
            audit.record(
                s,
                tenant_id,
                actor_type="system",
                actor_id=None,
                event="case.ai_rerun_result",
                entity_type="case",
                entity_id=case_id,
                payload={"trigger": trigger, "outcome": outcome},
            )
    except Exception:
        log.exception("could not audit the AI re-run of case %s", case_id)
    return {"outcome": outcome}


def due_for_retry(state: RerunState, now: datetime) -> bool:
    if state.auto_attempts >= MAX_AUTO_ATTEMPTS:
        return False
    return now >= state.escalated_at + BACKOFF_BASE * (2**state.auto_attempts)


def retry_ai_failures(
    engine: Engine, tenant_id: uuid.UUID, now: datetime | None = None
) -> list[str]:
    """Sweeper pass: re-run escalated AI-failure cases that are due, once the providers can be
    built again. Each case is claimed by request_rerun, so overlapping sweepers and staff
    presses start one run. Returns the case ids re-run."""
    now = now or datetime.now(UTC)
    with tenant_session(tenant_id, engine) as s:
        due = [
            c.id
            for c in s.scalars(
                select(Case).where(Case.status == "escalated").order_by(Case.updated_at).limit(50)
            )
            if (st := rerun_state(s, c)) is not None and due_for_retry(st, now)
        ]
    if not due or not agent_runner.providers_ready():  # no network; don't spend an attempt
        return []
    started = []
    for case_id in due:
        try:
            if request_rerun(engine, tenant_id, case_id, trigger="sweeper") == STARTED:
                run_requested(engine, tenant_id, case_id, "sweeper")
                started.append(str(case_id))
        except Exception:
            log.exception("sweeper: could not re-run the AI on case %s", case_id)
    return started
