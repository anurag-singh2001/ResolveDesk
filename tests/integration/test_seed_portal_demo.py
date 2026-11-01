"""seed_portal_demo against the test database: idempotent, demo-labelled, nothing else touched.
Never names a tenant. (Written, not yet run: the suite owns the databases.)"""

from datetime import UTC, datetime

from sqlalchemy import text

from scripts import seed_portal_demo as demo


def _counts(conn):
    return {
        t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
        for t in ("job_runs", "llm_usage", "error_logs", "alerts", "orders", "cases", "customers")
    }


def test_seed_is_idempotent_and_touches_only_demo_tables(owner_engine):
    now = datetime.now(UTC)
    with owner_engine.connect() as c:
        before = _counts(c)
    first = demo.seed(owner_engine, now)
    with owner_engine.connect() as c:
        mid = _counts(c)
    demo.seed(owner_engine, now)
    with owner_engine.connect() as c:
        after = _counts(c)
        orgs = c.execute(text("SELECT count(*) FROM organizations")).scalar()
        demo_jobs = c.execute(
            text("SELECT count(DISTINCT tenant_id) FROM job_runs WHERE job = :j"),
            {"j": demo.DEMO_JOB},
        ).scalar()
        open_alerts = c.execute(
            text("SELECT count(*) FROM alerts WHERE rule = :r AND status = 'open'"),
            {"r": demo.DEMO_RULE},
        ).scalar()
    assert mid == after
    assert first["tenants"] == orgs and demo_jobs == orgs
    assert open_alerts == 1
    for t in ("orders", "cases", "customers"):
        assert before[t] == after[t]
    with owner_engine.begin() as c:  # leave the test database as found
        c.execute(text("DELETE FROM job_runs WHERE job = :j"), {"j": demo.DEMO_JOB})
        c.execute(text("DELETE FROM llm_usage WHERE provider = 'demo'"))
        c.execute(text("DELETE FROM error_logs WHERE service = 'demo'"))
        c.execute(text("DELETE FROM alerts WHERE rule = :r"), {"r": demo.DEMO_RULE})
