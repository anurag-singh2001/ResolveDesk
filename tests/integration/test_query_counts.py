"""S12.3: slow pages are slow because every statement is a round trip to the remote database.
These tests count statements so a per-row or repeated query cannot creep back in.
For every tenant, never naming one."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select

from app.core.db import tenant_session
from app.core.models import Case, User
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
    assert len(text) <= 3


def test_rules_summary_endpoint_has_a_small_fixed_budget(api, app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    staff = next(u for u in cfg.users if u.role != "customer")
    headers = login(api, cfg.slug, staff.email)
    with _Count(app_engine) as c:
        assert api.get("/policies/rules-summary", headers=headers).status_code == 200
    # set_config + load_context + 3 reads for the summary; headroom of 2 for the driver.
    assert len(c.statements) <= 7, c.statements


def test_case_list_loads_orders_in_one_query(api, app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    headers = login(api, cfg.slug, hq.email)
    with tenant_session(tenant_id_for(cfg.slug), app_engine) as s:
        if s.scalar(select(Case.id).limit(1)) is None:
            pytest.skip("no cases in the seed to list")
        _ = s.scalar(select(User.id).limit(1))
    with _Count(app_engine) as c:
        assert api.get("/cases?limit=20", headers=headers).status_code == 200
    # Order rows come from one IN query, not one lookup per case.
    order_loads = [q for q in c.statements if "FROM transactions" in q]
    assert len(order_loads) <= 1, order_loads
