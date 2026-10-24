"""Tenant metadata the UI needs, so it never reads vertical packs or tenant files itself."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_context, tenant_db
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext

router = APIRouter(tags=["meta"])


class CategoriesOut(BaseModel):
    categories: list[str]


@router.get("/meta/categories")
def issue_categories(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> CategoriesOut:
    """The caller's tenant pack `issue_categories` (RLS: the session sees one organization).

    Any authenticated role may read it; `ctx` is here so a missing/invalid token is a 401.
    """
    return CategoriesOut(categories=list(tenant_pack(db).issue_categories))
