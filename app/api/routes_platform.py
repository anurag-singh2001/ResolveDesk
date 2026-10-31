"""Platform-admin routes (S9.1): sign-in and aggregate-only, cross-tenant reads.

Everything here answers 404 unless the platform admin is configured in the environment. Data
comes only from the aggregate views through the dedicated DB role (resolvedesk_platform): no
raw table, no tenant setting, no customer row. Every read writes a platform audit entry
(actor and route only).
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from app.api.deps import _bearer, not_found
from app.config import get_settings, platform_admin_enabled
from app.core.auth import AuthError
from app.core.db import get_engine
from app.core.platform_auth import (
    PlatformDisabled,
    PlatformLocked,
    WrongPrincipal,
    authenticate_platform,
    read_platform_token,
)


def _feature_on() -> None:
    if not platform_admin_enabled(get_settings()):
        raise not_found()


PLATFORM_ROLE = "resolvedesk_platform"

router = APIRouter(prefix="/platform", tags=["platform"], dependencies=[Depends(_feature_on)])


class PlatformLoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class PlatformTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class TenantRow(BaseModel):
    tenant_slug: str
    vertical_pack: str


class CaseCountRow(BaseModel):
    tenant_slug: str
    day: date
    status: str
    case_count: int


class ApprovalCountRow(BaseModel):
    tenant_slug: str
    day: date
    decision: str
    mode: str
    approval_count: int


class ActivityRow(BaseModel):
    tenant_slug: str
    last_system_event_at: datetime | None


class LlmUsageRow(BaseModel):
    tenant_slug: str
    day: date
    provider: str
    model: str
    purpose: str
    outcome: str
    run_count: int
    call_count: int
    failure_count: int
    tokens_in: int
    tokens_out: int
    cost_micro_paise: int
    latency_ms_total: int


class JobRunRow(BaseModel):
    tenant_slug: str
    day: date
    job: str
    status: str
    run_count: int
    duration_ms_total: int
    last_started_at: datetime | None


def get_platform_engine() -> Engine:
    """The aggregate-only connection. Tests override this dependency."""
    return get_engine(get_settings().platform_database_url)


def require_platform(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        return read_platform_token(creds.credentials)
    except WrongPrincipal:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "platform admin only") from None
    except PlatformDisabled:
        raise not_found() from None
    except AuthError:
        raise unauthorized from None


@router.post("/auth/login")
def platform_login(body: PlatformLoginIn) -> PlatformTokenOut:  # real time, not get_clock
    try:
        issued = authenticate_platform(body.email, body.password)
    except PlatformDisabled:
        raise not_found() from None
    except PlatformLocked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "too many failed logins, try again later"
        ) from None
    except AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials") from None
    return PlatformTokenOut(access_token=issued.token, expires_at=issued.expires_at)


def _read(engine: Engine, actor: str, route: str, sql: str) -> list[dict]:
    """Audit, then read one aggregate view, in one short transaction on the platform role."""
    with engine.begin() as conn:
        # Fail closed: only ever read as the aggregate-only role, whatever the URL says.
        if conn.execute(text("SELECT current_user")).scalar() != PLATFORM_ROLE:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "platform data unavailable")
        conn.execute(
            text("SELECT platform_audit_record(:actor, :route)"), {"actor": actor, "route": route}
        )
        return [dict(r) for r in conn.execute(text(sql)).mappings()]


@router.get("/tenants")
def tenants(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[TenantRow]:
    rows = _read(
        engine,
        actor,
        "GET /platform/tenants",
        "SELECT tenant_slug, vertical_pack FROM platform_tenants_v ORDER BY tenant_slug",
    )
    return [TenantRow(**r) for r in rows]


@router.get("/cases")
def case_counts(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[CaseCountRow]:
    rows = _read(
        engine,
        actor,
        "GET /platform/cases",
        "SELECT tenant_slug, day, status, case_count FROM platform_case_counts_v "
        "ORDER BY tenant_slug, day, status",
    )
    return [CaseCountRow(**r) for r in rows]


@router.get("/approvals")
def approval_counts(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[ApprovalCountRow]:
    rows = _read(
        engine,
        actor,
        "GET /platform/approvals",
        "SELECT tenant_slug, day, decision, mode, approval_count FROM platform_approval_counts_v "
        "ORDER BY tenant_slug, day, decision, mode",
    )
    return [ApprovalCountRow(**r) for r in rows]


@router.get("/activity")
def activity(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[ActivityRow]:
    rows = _read(
        engine,
        actor,
        "GET /platform/activity",
        "SELECT tenant_slug, last_system_event_at FROM platform_activity_v ORDER BY tenant_slug",
    )
    return [ActivityRow(**r) for r in rows]


@router.get("/ai-usage")
def ai_usage(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[LlmUsageRow]:
    rows = _read(
        engine,
        actor,
        "GET /platform/ai-usage",
        "SELECT tenant_slug, day, provider, model, purpose, outcome, run_count, call_count, "
        "failure_count, tokens_in, tokens_out, cost_micro_paise, latency_ms_total "
        "FROM platform_llm_usage_v "
        "ORDER BY tenant_slug, day, provider, model, purpose, outcome",
    )
    return [LlmUsageRow(**r) for r in rows]


@router.get("/jobs")
def job_runs(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[JobRunRow]:
    rows = _read(
        engine,
        actor,
        "GET /platform/jobs",
        "SELECT tenant_slug, day, job, status, run_count, duration_ms_total, last_started_at "
        "FROM platform_job_runs_v ORDER BY tenant_slug, day, job, status",
    )
    return [JobRunRow(**r) for r in rows]
