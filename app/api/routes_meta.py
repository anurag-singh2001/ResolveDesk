"""Tenant metadata the UI needs, so it never reads vertical packs or tenant files itself."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_context, tenant_db
from app.config import get_settings
from app.core.settings_resolver import effective_settings, tenant_pack
from app.core.tenancy import TenantContext

router = APIRouter(tags=["meta"])


class CategoriesOut(BaseModel):
    categories: list[str]
    free_text: bool  # agents mode: a customer may describe the problem without a category


@router.get("/meta/categories")
def issue_categories(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> CategoriesOut:
    """The caller's tenant pack `issue_categories` (RLS: the session sees one organization).

    Any authenticated role may read it; `ctx` is here so a missing/invalid token is a 401.
    """
    return CategoriesOut(
        categories=list(tenant_pack(db).issue_categories),
        free_text=get_settings().engine_mode == "agents",
    )


class PrivacyContactOut(BaseModel):
    name: str
    email: str


@router.get("/meta/privacy")
def privacy_contact(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> PrivacyContactOut:
    """The caller's tenant privacy contact (RLS: one organization), for the Help page and the
    footer. Any signed-in role. Provisional wording, not legal advice."""
    s = effective_settings(db)
    return PrivacyContactOut(name=s["privacy_contact_name"], email=s["privacy_contact_email"])
