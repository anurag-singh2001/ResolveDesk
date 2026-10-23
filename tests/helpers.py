from fastapi.testclient import TestClient

from app.config import get_settings


def login(api: TestClient, tenant_slug: str, email: str) -> dict[str, str]:
    """Bearer header for a seeded demo user."""
    resp = api.post(
        "/auth/login",
        json={"tenant": tenant_slug, "email": email, "password": get_settings().demo_password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
