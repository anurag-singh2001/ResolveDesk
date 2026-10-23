"""Dev-only controls (PROJECT.md section 12). Not mounted when APP_ENV=prod.

Chaos is process-wide (one set of mock providers serves every tenant), so only an hq_owner
may change it, and only outside prod.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_tenant_context
from app.core.tenancy import TenantContext
from mocks.base import Chaos
from mocks.registry import chaos_state, mock_names, set_chaos

router = APIRouter(prefix="/admin", tags=["admin (dev only)"])


class ChaosIn(BaseModel):
    service: str
    timeout_rate: float = Field(0.0, ge=0, le=1)
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
def get_chaos(_: TenantContext = Depends(_hq_only)) -> dict[str, dict]:
    return chaos_state()


@router.post("/chaos")
def post_chaos(body: ChaosIn, _: TenantContext = Depends(_hq_only)) -> dict[str, dict]:
    if body.service not in mock_names():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown service {body.service}"
        )
    set_chaos(body.service, Chaos(**body.model_dump(exclude={"service"})))
    return chaos_state()
