"""Run an approved proposal with the executor for its action.

Called only after the decision has committed (a background task, the agent run after its
propose step, or the sweeper), so no DB transaction is open during the provider call
(hard rule 5). Every executor uses a stable key per proposal, so calling this twice for one
proposal (a retry, the sweeper racing the background task) still writes once.
"""

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import Engine

from app.core.tenancy import TenantContext
from app.engine.executor import ExecutionRefused, execute_refund, reconcile_refund
from app.engine.voucher_executor import execute_voucher, reconcile_voucher

log = logging.getLogger(__name__)

# action -> (execute, reconcile). Actions not listed have no executor yet.
EXECUTORS: dict[str, tuple[Callable, Callable]] = {
    "refund": (execute_refund, reconcile_refund),
    "free_item_voucher": (execute_voucher, reconcile_voucher),
}


def executable(action: str) -> bool:
    return action in EXECUTORS


def system_context(tenant_id: uuid.UUID) -> TenantContext:
    """Executors only use the tenant id (sessions, provider account); never a role check."""
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a UUID from the auth/system context")
    return TenantContext(
        tenant_id, uuid.UUID(int=0), uuid.UUID(int=0), "hq_owner", frozenset(), frozenset()
    )


def run_approved(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, action: str):
    """Execute one approved proposal. Refusals are recorded by the executor; nothing raises."""
    if not executable(action):
        return None
    execute, _ = EXECUTORS[action]
    try:
        return execute(engine, system_context(tenant_id), proposal_id)
    except ExecutionRefused as exc:
        log.info("%s %s not executed: %s", action, proposal_id, exc.reason)
        return None


def reconcile(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, action: str):
    """Ask the provider about an unfinished execution, by its key."""
    if not executable(action):
        return None
    _, rec = EXECUTORS[action]
    try:
        return rec(engine, system_context(tenant_id), proposal_id)
    except ExecutionRefused as exc:
        log.info("%s %s not reconciled: %s", action, proposal_id, exc.reason)
        return None
