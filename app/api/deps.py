"""FastAPI dependencies: the tenant comes from the verified token, never from the request."""

from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.auth import AuthError, read_token
from app.core.db import get_engine, tenant_session
from app.core.tenancy import TenantContext, load_context

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


def get_db_engine() -> Engine:
    return get_engine()


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
