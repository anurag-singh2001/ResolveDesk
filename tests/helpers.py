import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import get_settings
from app.core.db import tenant_session
from app.core.models import Case, Ticket
from app.core.tenancy import tenant_id_for
from evals.harness import undo_planted


def login(api: TestClient, tenant_slug: str, email: str) -> dict[str, str]:
    """Bearer header for a seeded demo user."""
    resp = api.post(
        "/auth/login",
        json={"tenant": tenant_slug, "email": email, "password": get_settings().demo_password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ~5% of configured history volumes: enough rows for scope tests, quick on Neon.
HISTORY_SCALE = 0.05


def remove_eval_cases(app_engine, maint_engine, slug: str, results, planted) -> None:
    """Undo an eval-harness pass in the test DB: its cases (proposals, approvals and runs
    cascade) and what its selectors changed (short items, re-dated orders)."""
    tid = tenant_id_for(slug)
    mine = [uuid.UUID(r.case_id) for r in results]
    with tenant_session(tid, maint_engine) as s:
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(mine)))
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id.in_(mine)))
    with tenant_session(tid, app_engine) as s:
        undo_planted(s, planted)
