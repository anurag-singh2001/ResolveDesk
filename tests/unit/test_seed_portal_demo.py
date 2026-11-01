"""scripts/seed_portal_demo.py: the dev-only guard and the shape of the demo rows (no database)."""

import uuid
from datetime import UTC, datetime

import pytest

from scripts import seed_portal_demo as demo

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("env", ["prod", "test", ""])
def test_refuses_outside_dev(env):
    assert demo.refusal(env, "postgresql://x") is not None


def test_refuses_without_owner_url_and_allows_dev():
    assert demo.refusal("dev", None) is not None
    assert demo.refusal("dev", "postgresql://x") is None


def test_rows_are_labelled_demo_and_stable():
    tid = uuid.uuid4()
    rows = demo.tenant_rows(tid, NOW)
    assert rows == demo.tenant_rows(tid, NOW)
    assert all(r["job"].startswith("demo") and r["tenant_id"] == tid for r in rows["jobs"])
    assert all(r["provider"] == "demo" and r["model"].startswith("demo") for r in rows["usage"])
    assert {r["status"] for r in rows["jobs"]} == {"ok", "failed"}
    assert all(isinstance(r["estimated_cost_micro_paise"], int) for r in rows["usage"])


def test_ids_differ_per_tenant():
    a, b = demo.tenant_rows(uuid.uuid4(), NOW), demo.tenant_rows(uuid.uuid4(), NOW)
    ids = [r["id"] for r in a["jobs"] + a["usage"] + b["jobs"] + b["usage"]]
    assert len(set(ids)) == len(ids)


def test_script_touches_only_the_demo_tables():
    sql = " ".join(
        str(s) for s in (demo._JOB_SQL, demo._USAGE_SQL, demo._ERROR_SQL, demo._ALERT_SQL)
    )
    for table in ("customers", "orders", "cases", "refunds", "proposals", "payments"):
        assert table not in sql.lower()
