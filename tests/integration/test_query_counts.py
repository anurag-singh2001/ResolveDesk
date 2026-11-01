"""S12.3: slow pages are slow because every statement is a round trip to the remote database.
These tests count statements so a per-row or repeated query cannot creep back in.
For every tenant, never naming one."""

from datetime import UTC, datetime

from sqlalchemy import event

from app.core.db import tenant_session
from app.core.tenancy import tenant_id_for
from app.engine.rules_summary import build_rules_summary
from tests.helpers import login


class _Count:
    def __init__(self, engine):
        self.engine, self.statements = engine, []

    def _on(self, conn, cursor, statement, *_):
        self.statements.append(statement)

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *_):
        event.remove(self.engine, "before_cursor_execute", self._on)


def test_rules_summary_reads_each_table_once(app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s, _Count(app_engine) as c:
        build_rules_summary(s, "en", datetime.now(UTC), staff=True)
    text = [q.lower() for q in c.statements]
    assert sum("from tenant_settings" in q for q in text) == 1
    assert sum("from vertical_packs" in q for q in text) == 1
    assert sum("from policy_documents" in q for q in text) == 1
    assert len(text) <= 3, text  # measured: 3


def test_rules_summary_endpoint_has_a_small_fixed_budget(api, app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    staff = next(u for u in cfg.users if u.role != "customer")
    headers = login(api, cfg.slug, staff.email)
    with _Count(app_engine) as c:
        assert api.get("/policies/rules-summary", headers=headers).status_code == 200
    # measured 5: set_config, load_context, pack, setting rows, policy documents.
    assert len(c.statements) <= 5, c.statements  # measured: 5
