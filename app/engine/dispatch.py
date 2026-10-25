"""The executor table (action -> execute, reconcile) and thin entry points into the single
execution path in app/engine/lifecycle.py.

Called only after the decision has committed (a background task, the graph's execute node,
or the sweeper), so no DB transaction is open during the provider call (hard rule 5). Every
executor uses a stable key per proposal, so calling this twice for one proposal (a retry,
the sweeper racing the background task, the graph resume racing the decision fallback)
still writes once.
"""

import uuid
from collections.abc import Callable

from sqlalchemy import Engine

from app.core.tenancy import TenantContext
from app.engine.executor import execute_refund, reconcile_refund
from app.engine.voucher_executor import execute_voucher, reconcile_voucher

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


def run_approved(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, action: str = ""):
    """Execute one approved proposal, then verify it: a thin call into the single execution
    path (lifecycle.execute_and_verify). The action is read from the proposal, so a caller's
    `action` is never trusted. Refusals are recorded and escalated there; nothing raises for
    them. Imported lazily because lifecycle builds on this module's executor table."""
    from app.engine import lifecycle

    return lifecycle.execute_and_verify(engine, tenant_id, proposal_id)


def reconcile(engine: Engine, tenant_id: uuid.UUID, proposal_id: uuid.UUID, action: str = ""):
    """Ask the provider about an unfinished execution, by its key, then verify: a thin call
    into lifecycle.reconcile_and_verify."""
    from app.engine import lifecycle

    return lifecycle.reconcile_and_verify(engine, tenant_id, proposal_id)
