"""Platform-admin routes (S9.1): sign-in and aggregate-only, cross-tenant reads.

Everything here answers 404 unless the platform admin is configured in the environment. Data
comes only from the aggregate views through the dedicated DB role (resolvedesk_platform): no
raw table, no tenant setting, no customer row. Every read writes a platform audit entry
(actor and route only).
"""

import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from app.api.deps import _bearer
from app.config import get_settings, platform_admin_enabled
from app.core import scenario_lab as lab
from app.core.auth import AuthError
from app.core.db import get_engine
from app.core.platform_auth import (
    PlatformDisabled,
    PlatformLocked,
    WrongPrincipal,
    authenticate_platform,
    read_platform_token,
)
from evals.scenarios import ScenarioError

NOT_ENABLED_DETAIL = "platform admin not enabled"  # the portal tells "off" from any other 404


def _off() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, NOT_ENABLED_DETAIL)


def _feature_on() -> None:
    if not platform_admin_enabled(get_settings()):
        raise _off()


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


class AlertRow(BaseModel):
    rule: str
    scope: str
    status: str
    value: int
    threshold: int
    opened_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


class ErrorLogRow(BaseModel):
    service: str
    level: str
    event_code: str
    error_class: str
    day: date
    occurrences: int
    last_at: datetime


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
    finished_count: int
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
        raise _off() from None
    except AuthError:
        raise unauthorized from None


@router.post("/auth/login")
def platform_login(body: PlatformLoginIn) -> PlatformTokenOut:  # real time, not get_clock
    try:
        issued = authenticate_platform(body.email, body.password)
    except PlatformDisabled:
        raise _off() from None
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


@router.get("/alerts")
def alerts(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[AlertRow]:
    """Open alerts first, then recently resolved ones (S9.4). Nothing is sent anywhere."""
    rows = _read(
        engine,
        actor,
        "GET /platform/alerts",
        "SELECT rule, scope, status, value, threshold, opened_at, last_seen_at, resolved_at "
        "FROM platform_alerts_v WHERE status = 'open' OR resolved_at > now() - interval '7 days' "
        "ORDER BY (status = 'open') DESC, opened_at DESC LIMIT 200",
    )
    return [AlertRow(**r) for r in rows]


@router.get("/logs")
def logs(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> list[ErrorLogRow]:
    """Error counts by service, level, event code and exception class, last 14 days (S9.4)."""
    rows = _read(
        engine,
        actor,
        "GET /platform/logs",
        "SELECT service, level, event_code, error_class, day, occurrences, last_at "
        "FROM platform_error_logs_v WHERE day >= (now() AT TIME ZONE 'UTC')::date - 14 "
        "ORDER BY day DESC, occurrences DESC LIMIT 500",
    )
    return [ErrorLogRow(**r) for r in rows]


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
        "SELECT tenant_slug, day, job, status, run_count, finished_count, duration_ms_total, "
        "last_started_at "
        "FROM platform_job_runs_v ORDER BY tenant_slug, day, job, status",
    )
    return [JobRunRow(**r) for r in rows]


# --- Scenario lab (S10.1) -----------------------------------------------------------------
# Scenario files are repo data, not DB rows: nothing here widens the platform role. Each call
# still writes the platform audit entry (actor and route only). Runs go to the scratch DB only.


class LabTextIn(BaseModel):
    yaml: str = Field(max_length=20_000)


class LabRunIn(BaseModel):
    tenant: str = Field(max_length=64)
    ids: list[str] = Field(max_length=lab.MAX_IDS, min_length=1)
    pipeline: str = Field(default="agents", max_length=16)


def _tag(value: str, limit: int = 64) -> str:
    """Untrusted text made safe for the audit route: a short [a-z0-9._-] token."""
    return re.sub(r"[^A-Za-z0-9._-]", "?", value)[:limit]


def _audit(engine: Engine, actor: str, route: str, **detail: str) -> None:
    """Audit entry with the route and (tenant, scenario id, pipeline) detail; no scenario text."""
    suffix = "".join(f" {k}={_tag(v, 200)}" for k, v in detail.items())
    _read(engine, actor, f"{route}{suffix}"[:200], "SELECT 1")


def _bad(exc: ScenarioError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"problems": exc.problems})


def _run_out() -> dict:
    st = lab.current()
    return {**st.__dict__, "comparison": lab.run_result(st)}


@router.get("/lab/scenarios")
def lab_scenarios(
    tenant: str = "",
    actor: str = Depends(require_platform),
    engine: Engine = Depends(get_platform_engine),
) -> dict:
    """No tenant: just the tenant list (the page's first call)."""
    _audit(engine, actor, "GET /platform/lab/scenarios", tenant=tenant)
    try:
        items = lab.list_scenarios(tenant) if tenant else []
    except ScenarioError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.problems[0]) from None
    return {
        "tenants": lab.list_tenants(),
        "scratch_configured": lab.scratch_configured(get_settings()),
        "scenarios": [
            {"id": x.id, "kind": x.kind, "held_out": x.held_out, "message": x.message[:200]}
            for x in items
        ],
    }


@router.get("/lab/scenarios/{tenant}/{scenario_id}")
def lab_scenario(
    tenant: str,
    scenario_id: str,
    actor: str = Depends(require_platform),
    engine: Engine = Depends(get_platform_engine),
) -> dict:
    _audit(engine, actor, "GET /platform/lab/scenarios/item", tenant=tenant, id=scenario_id)
    try:
        return {"yaml": lab.read_text(tenant, scenario_id)}
    except (ScenarioError, FileNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scenario not found") from None


@router.post("/lab/validate/{tenant}")
def lab_validate(
    tenant: str,
    body: LabTextIn,
    actor: str = Depends(require_platform),
    engine: Engine = Depends(get_platform_engine),
) -> dict:
    _audit(engine, actor, "POST /platform/lab/validate", tenant=tenant)
    try:
        sc = lab.validate_text(tenant, body.yaml)
    except ScenarioError as exc:
        if exc.problems == ["unknown tenant"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant") from None
        return {"ok": False, "problems": exc.problems}
    return {"ok": True, "problems": [], "id": sc.id}


@router.put("/lab/scenarios/{tenant}/{scenario_id}")
def lab_save(
    tenant: str,
    scenario_id: str,
    body: LabTextIn,
    actor: str = Depends(require_platform),
    engine: Engine = Depends(get_platform_engine),
) -> dict:
    _audit(engine, actor, "PUT /platform/lab/scenarios/item", tenant=tenant, id=scenario_id)
    try:
        sc = lab.save_text(tenant, scenario_id, body.yaml)
    except ScenarioError as exc:
        if exc.problems == ["unknown tenant"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant") from None
        raise _bad(exc) from None
    return {"ok": True, "id": sc.id}


@router.post("/lab/runs", status_code=status.HTTP_202_ACCEPTED)
def lab_start(
    body: LabRunIn,
    actor: str = Depends(require_platform),
    engine: Engine = Depends(get_platform_engine),
) -> dict:
    """Starts a background run and returns at once; poll GET /lab/runs/current."""
    _audit(
        engine, actor, "POST /platform/lab/runs",
        tenant=body.tenant, pipeline=body.pipeline, ids=",".join(body.ids),
    )  # fmt: skip
    try:
        lab.start_run(get_settings(), body.tenant, body.ids, body.pipeline)
    except lab.LabRefused as exc:
        busy = "already" in str(exc)
        code = status.HTTP_409_CONFLICT if busy else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(code, str(exc)) from None
    except ScenarioError as exc:
        if exc.problems == ["unknown tenant"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown tenant") from None
        raise _bad(exc) from None
    return _run_out()


@router.get("/lab/runs/current")
def lab_current(
    actor: str = Depends(require_platform), engine: Engine = Depends(get_platform_engine)
) -> dict:
    _audit(engine, actor, "GET /platform/lab/runs/current")
    return _run_out()
