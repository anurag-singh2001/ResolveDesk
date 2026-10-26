"""Dev-only controls (PROJECT.md section 12). Mounted only when APP_ENV is dev or test.

Chaos is per merchant: an hq_owner sets and sees failure injection for their own tenant's
provider accounts only, never another tenant's.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from app.api.deps import _UNAUTHORIZED, _bearer, get_db_engine, get_tenant_context
from app.core.auth import AuthError, read_token
from app.core.db import tenant_session
from app.core.tenancy import TenantContext, load_context
from app.engine.sweeper import sweep_tenant
from mocks.base import Chaos
from mocks.registry import chaos_state, merchant_id_for, mock_names, set_chaos

router = APIRouter(prefix="/admin", tags=["admin (dev only)"])
DEV_ENVS = frozenset({"dev", "test"})


class ChaosIn(BaseModel):
    service: str
    timeout_rate: float = Field(0.0, ge=0, le=1)
    transient_error_rate: float = Field(0.0, ge=0, le=1)
    accept_then_timeout_rate: float = Field(0.0, ge=0, le=1)
    error_rate: float = Field(0.0, ge=0, le=1)
    processing_rate: float = Field(0.0, ge=0, le=1)
    settle_after_polls: int = Field(2, ge=1, le=100)
    delay_ms: int = Field(0, ge=0, le=30_000)
    seed: int = 0


def _hq_only(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if ctx.role != "hq_owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hq_owner only")
    return ctx


@router.get("/chaos")
def get_chaos(ctx: TenantContext = Depends(_hq_only)) -> dict[str, dict]:
    return chaos_state(merchant_id_for(ctx.tenant_id))


@router.post("/chaos")
def post_chaos(body: ChaosIn, ctx: TenantContext = Depends(_hq_only)) -> dict[str, dict]:
    if body.service not in mock_names():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown service {body.service}"
        )
    merchant = merchant_id_for(ctx.tenant_id)
    set_chaos(body.service, Chaos(**body.model_dump(exclude={"service"})), merchant)
    return chaos_state(merchant)


def _hq_ctx_no_session(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    engine: Engine = Depends(get_db_engine),
) -> TenantContext:
    """Like _hq_only, but the auth transaction is closed before the route body runs: the sweep
    calls payment providers, and no network call may happen inside an open transaction."""
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
    if ctx.role != "hq_owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hq_owner only")
    return ctx


@router.post("/sweep")
def post_sweep(
    ctx: TenantContext = Depends(_hq_ctx_no_session),
    engine: Engine = Depends(get_db_engine),
) -> dict:
    """Run the crash-recovery sweep (`make sweep`) for the caller's own tenant, taken from
    the token. The sweeper opens its own short transactions."""
    return asdict(sweep_tenant(engine, ctx.tenant_id))
