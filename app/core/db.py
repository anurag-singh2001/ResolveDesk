"""Engine and tenant-scoped sessions.

The tenant is set with set_config(..., is_local=true), so it lives only for the current
transaction. Neon's pooled endpoint (PgBouncer, transaction mode) hands connections to other
clients between transactions; a session-level SET could leak one tenant into another request.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    # pre_ping: Neon suspends idle computes, so pooled connections can go stale.
    return create_engine(url, pool_pre_ping=True)


@contextmanager
def tenant_session(tenant_id: uuid.UUID, engine: Engine | None = None) -> Iterator[Session]:
    """One transaction scoped to tenant_id. tenant_id must come from the auth context only."""
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a UUID from the auth context")
    with Session(engine or get_engine()) as session, session.begin():
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        yield session
