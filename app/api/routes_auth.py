import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_db_engine, get_tenant_context, not_found, tenant_db
from app.config import get_settings
from app.core import audit
from app.core.auth import InvalidCredentials, LockedOut, authenticate
from app.core.models import Customer, FeatureFlag, Organization, User
from app.core.tenancy import TenantContext
from app.core.tenant_config import load_tenant, tenant_dirs

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    tenant: str = Field(max_length=64)
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class TenantOut(BaseModel):
    slug: str
    name: str
    vertical: str


class MeOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: str
    location_ids: list[uuid.UUID]
    brand_ids: list[uuid.UUID]
    tenant: TenantOut
    growth_enabled: bool  # the tenant's `growth` flag: the UI shows Growth only when it is on


class DemoAccountOut(BaseModel):
    tenant: str
    email: str
    name: str
    role: str
    password: str


@router.post("/auth/login")
def login(
    body: LoginIn,
    engine: Engine = Depends(get_db_engine),
    now: datetime = Depends(get_clock),
) -> TokenOut:
    try:
        issued = authenticate(engine, body.tenant, body.email, body.password, now=now)
    except LockedOut:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "too many failed logins, try again later"
        ) from None
    except InvalidCredentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials") from None
    return TokenOut(access_token=issued.token, expires_at=issued.expires_at)


@router.get("/auth/businesses")
def businesses(engine: Engine = Depends(get_db_engine)) -> list[TenantOut]:
    """What a login screen needs to offer a business picker: slug, name, vertical. Read
    through a narrow SECURITY DEFINER function (migration 0013); RLS stays on for the rest."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT slug, name, vertical_pack FROM public_businesses()"))
        return [TenantOut(slug=r.slug, name=r.name, vertical=r.vertical_pack) for r in rows]


def demo_accounts_enabled() -> bool:
    s = get_settings()
    return s.demo_auth and s.app_env != "prod"


@router.get("/auth/demo-accounts")
def demo_accounts() -> list[DemoAccountOut]:
    """Dev only: the seeded demo users and their demo passwords, from the tenant folders.
    404 in prod or with DEMO_AUTH off (the passwords aren't seeded then either)."""
    if not demo_accounts_enabled():
        raise not_found()
    out = []
    for folder in tenant_dirs():
        cfg = load_tenant(folder)
        for user in cfg.users:
            password = cfg.demo_password_for(user)
            if password is not None:
                out.append(
                    DemoAccountOut(
                        tenant=cfg.slug,
                        email=user.email,
                        name=user.name,
                        role=user.role,
                        password=password,
                    )
                )
    return out


@router.get("/me")
def me(ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)) -> MeOut:
    user = db.get(User, ctx.user_id)  # same RLS-scoped session the context was built in
    org = db.get(Organization, ctx.tenant_id)
    if user is None or org is None:  # unreachable while the context exists; fail closed anyway
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return MeOut(
        user_id=ctx.user_id,
        name=user.display_name,
        email=user.email,
        role=ctx.role,
        location_ids=sorted(ctx.location_ids),
        brand_ids=sorted(ctx.brand_ids),
        tenant=TenantOut(slug=org.slug, name=org.name, vertical=org.vertical_pack),
        growth_enabled=bool(
            db.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == "growth"))
        ),
    )


class PreferencesIO(BaseModel):
    language: Literal["en", "hi-Latn", "hi"]


def _own_customer(ctx: TenantContext, db: Session) -> Customer:
    """The caller's own customer record (found by their login), else 404: staff and users
    without a customer record have no preferences, and no id from the request is used."""
    customer = db.scalar(select(Customer).where(Customer.user_id == ctx.user_id))
    if ctx.role != "customer" or customer is None:
        raise not_found()
    return customer


@router.get("/me/preferences")
def get_preferences(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> PreferencesIO:
    return PreferencesIO(language=_own_customer(ctx, db).preferred_language)


@router.put("/me/preferences")
def set_preferences(
    body: PreferencesIO,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> PreferencesIO:
    """The customer's own choice of language for the messages we send them (S5.6)."""
    customer = _own_customer(ctx, db)
    if customer.preferred_language != body.language:
        audit.record(
            db,
            ctx.tenant_id,
            actor_type="user",
            actor_id=ctx.user_id,
            event="customer.language_changed",
            entity_type="customer",
            entity_id=customer.id,
            payload={"before": customer.preferred_language, "after": body.language},
        )
        customer.preferred_language = body.language
    return PreferencesIO(language=customer.preferred_language)
