"""FastAPI dependencies: the tenant comes from the verified token, never from the request."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import AuthError, read_token
from app.core.db import get_engine, tenant_session
from app.core.tenancy import TenantContext, load_context

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


def get_db_engine() -> Engine:
    return get_engine()


MAX_CLOCK_OFFSET = timedelta(days=60)
CLOCK_ENVS = frozenset({"dev", "test"})  # the only environments where the offset exists
_clock_lock = threading.Lock()
_clock_offset = timedelta(0)


def clock_offset() -> timedelta:
    with _clock_lock:
        return _clock_offset


def advance_clock(by: timedelta) -> timedelta:
    """Move the simulated clock forward, capped at MAX_CLOCK_OFFSET and never below zero, so
    simulated time can never be earlier than real time. Returns the new offset."""
    global _clock_offset
    with _clock_lock:
        _clock_offset = min(max(_clock_offset + by, timedelta(0)), MAX_CLOCK_OFFSET)
        return _clock_offset


def reset_clock() -> None:
    global _clock_offset
    with _clock_lock:
        _clock_offset = timedelta(0)


def get_clock() -> datetime:
    """Now, as a dependency so tests can move time (e.g. past the login lockout window).
    In dev/test the dev panel's offset (POST /admin/clock) is added; in any other APP_ENV
    the offset is ignored."""
    now = datetime.now(UTC)
    if get_settings().app_env in CLOCK_ENVS:
        now += clock_offset()
    return now


def _request_session(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    engine: Engine = Depends(get_db_engine),
) -> Iterator[Session]:
    """One tenant-scoped transaction per request. The caller's role/scope is read in the same
    transaction the route then uses, so the access decision and the data can't disagree.
    FastAPI caches this per request: get_tenant_context and tenant_db share it.

    scope="function" (where it's used): the transaction commits as soon as the endpoint
    returns, before the response is sent and before background tasks run. So a decision is
    committed before its refund starts, and no request transaction is ever open while a
    background task talks to a provider (hard rule 5)."""
    if creds is None:
        raise _UNAUTHORIZED
    try:
        tenant_id, user_id = read_token(creds.credentials)
    except AuthError:
        raise _UNAUTHORIZED from None
    with tenant_session(tenant_id, engine) as session:
        ctx = load_context(session, tenant_id, user_id)
        if ctx is None:
            raise _UNAUTHORIZED
        session.info["ctx"] = ctx
        yield session


def get_tenant_context(
    session: Session = Depends(_request_session, scope="function"),
) -> TenantContext:
    return session.info["ctx"]


def tenant_db(session: Session = Depends(_request_session, scope="function")) -> Session:
    """The request's session, scoped (RLS) to the caller's tenant."""
    return session


def require_staff(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if not ctx.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "staff only")
    return ctx


def not_found() -> HTTPException:
    """Out of scope and other-tenant records look the same: absent (hard rule 8)."""
    return HTTPException(status.HTTP_404_NOT_FOUND, "not found")
