import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_db_engine, get_tenant_context, tenant_db
from app.core.auth import authenticate
from app.core.models import User
from app.core.tenancy import TenantContext

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    tenant: str
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: str
    location_ids: list[uuid.UUID]
    brand_ids: list[uuid.UUID]


@router.post("/auth/login")
def login(body: LoginIn, engine: Engine = Depends(get_db_engine)) -> TokenOut:
    token = authenticate(engine, body.tenant, body.email, body.password)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenOut(access_token=token)


@router.get("/me")
def me(ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)) -> MeOut:
    user = db.get(User, ctx.user_id)  # same RLS-scoped session the context was built in
    if user is None:  # unreachable while the context exists; fail closed anyway
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return MeOut(
        user_id=ctx.user_id,
        name=user.display_name,
        email=user.email,
        role=ctx.role,
        location_ids=sorted(ctx.location_ids),
        brand_ids=sorted(ctx.brand_ids),
    )
