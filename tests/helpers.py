from functools import lru_cache

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete

from app.core.db import tenant_session
from app.core.models import LoginFailure
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import TENANTS_DIR, TenantConfig, load_tenant


@lru_cache
def _tenant_cfg(tenant_slug: str) -> TenantConfig:
    return load_tenant(TENANTS_DIR / tenant_slug)


def demo_password(tenant_slug: str, email: str) -> str:
    """The demo password the tenant folder gives this user (seeded with DEMO_AUTH=true)."""
    cfg = _tenant_cfg(tenant_slug)
    user = next(u for u in cfg.users if u.email == email)
    password = cfg.demo_password_for(user)
    assert password is not None, f"{email} has no demo password"
    return password


def login(api: TestClient, tenant_slug: str, email: str) -> dict[str, str]:
    """Bearer header for a seeded demo user."""
    resp = api.post(
        "/auth/login",
        json={"tenant": tenant_slug, "email": email, "password": demo_password(tenant_slug, email)},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ~5% of configured history volumes: enough rows for scope tests, quick on Neon.
HISTORY_SCALE = 0.05


def clear_login_failures(engine: Engine, tenant_slug: str) -> None:
    """Forget failed logins (lockout counters) for one tenant."""
    with tenant_session(tenant_id_for(tenant_slug), engine) as s:
        s.execute(delete(LoginFailure))
