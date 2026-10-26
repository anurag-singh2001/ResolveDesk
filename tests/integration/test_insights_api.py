"""GET /insights/outlets: scope by role, money as integers, and the growth flag on /me.

Runs for every tenant folder and never names one: who sees what comes from the users' roles.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.models import Case, RefundOperation, Transaction, User
from app.core.money import percent_of
from app.core.tenancy import load_context, tenant_id_for
from app.engine.approvals import decide
from app.engine.eligibility import order_facts
from app.engine.executor import execute_refund
from app.engine.proposals import create_proposal
from app.engine.voucher_executor import execute_voucher
from mocks.registry import reset_mocks
from tests.helpers import login

MONEY = ("refunds_confirmed_paise", "vouchers_issued_paise")
COUNTS = ("cases_opened", "refunds_confirmed_count", "vouchers_issued_count", "orders")


def _users(cfg, role):
    return [u for u in cfg.users if u.role == role]


def test_needs_a_token(api):
    assert api.get("/insights/outlets").status_code == 401


def test_only_hq_and_franchisee_owners_may_read(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    for user in cfg.users:
        resp = api.get("/insights/outlets", headers=login(api, cfg.slug, user.email))
        if user.role in ("hq_owner", "franchisee_owner"):
            assert resp.status_code == 200, user.email
        else:
            assert resp.status_code == 403, user.email


def test_hq_sees_every_location_of_its_own_tenant_only(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    for user in _users(cfg, "hq_owner"):
        headers = login(api, cfg.slug, user.email)
        rows = api.get("/insights/outlets", headers=headers).json()
        mine = {loc["id"] for loc in api.get("/locations", headers=headers).json()}
        assert mine  # the tenant has locations
        assert {r["location_id"] for r in rows} == mine  # all of them, and no other tenant's


def test_franchisee_sees_only_their_own_locations(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    for user in _users(cfg, "franchisee_owner"):
        headers = login(api, cfg.slug, user.email)
        own = set(api.get("/me", headers=headers).json()["location_ids"])
        everything = api.get("/insights/outlets", headers=login(api, cfg.slug, _hq(cfg))).json()
        rows = api.get("/insights/outlets", headers=headers).json()
        assert {r["location_id"] for r in rows} == own
        if len(everything) > len(own):  # strictly narrower than HQ's view
            assert len(rows) < len(everything)


def _hq(cfg) -> str:
    return _users(cfg, "hq_owner")[0].email


def test_metrics_are_integers_and_consistent(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    rows = api.get("/insights/outlets", headers=login(api, cfg.slug, _hq(cfg))).json()
    assert rows
    for r in rows:
        assert r["name"]
        for key in (*MONEY, *COUNTS):
            assert type(r[key]) is int and r[key] >= 0, key
        # A count of zero means a total of zero (and the reverse).
        assert (r["refunds_confirmed_count"] == 0) == (r["refunds_confirmed_paise"] == 0)
        assert (r["vouchers_issued_count"] == 0) == (r["vouchers_issued_paise"] == 0)
        assert r["median_decision_minutes"] is None or r["median_decision_minutes"] >= 0
        if r["orders"] == 0:
            assert r["repeat_rate_bp"] is None
        else:
            assert type(r["repeat_rate_bp"]) is int and 0 <= r["repeat_rate_bp"] <= 10000


@pytest.mark.parametrize("flag_role", ["hq_owner", "location_manager", "customer"])
def test_me_reports_the_growth_flag(api, seeded, tenant, flag_role):
    cfg = seeded[tenant.name]
    for user in _users(cfg, flag_role):
        me = api.get("/me", headers=login(api, cfg.slug, user.email)).json()
        assert me["growth_enabled"] is bool(cfg.feature_flags.get("growth"))


@pytest.fixture
def money_moved(app_engine, maint_engine, seeded_history, tenant):
    """One case on an order at a franchisee's location, with an approved, executed refund and
    an approved, executed voucher, so the insight money fields are non-zero. Mocks reset after."""
    cfg = seeded_history[tenant.name]
    franchisees = _users(cfg, "franchisee_owner")
    if not franchisees:
        pytest.skip("this tenant has no franchisee_owner, so there is no scope to compare")
    tid = tenant_id_for(cfg.slug)
    reset_mocks()
    now = datetime.now(UTC)
    hq_email = _hq(cfg)
    with tenant_session(tid, app_engine) as s:
        fr_user = s.scalar(select(User).where(User.email == franchisees[0].email))
        fr = load_context(s, tid, fr_user.id)
        hq = load_context(s, tid, s.scalar(select(User.id).where(User.email == hq_email)))
        order = s.scalars(
            select(Transaction)
            .where(Transaction.location_id.in_(list(fr.location_ids)))
            .order_by(Transaction.total_paise.desc(), Transaction.id)
            .limit(1)
        ).one()
        _, facts = order_facts(s, order.id)
        settings = facts.settings
        amount = max(
            1,
            min(
                percent_of(order.total_paise, settings["refund_max_percent"]),
                settings["refund_without_escalation_paise"],
            )
            // 2,
        )
        case_id = uuid.uuid4()
        s.add(
            Case(
                id=case_id,
                tenant_id=tid,
                customer_id=order.customer_id,
                transaction_id=order.id,
                status="awaiting_approval",
                channel="app",
                opened_at=now,
            )
        )
        s.flush()
        order_id, location_id = order.id, order.location_id
        refund = create_proposal(
            s,
            tid,
            case_id=case_id,
            action="refund",
            reason="policy",
            params={"transaction_id": str(order_id), "amount_paise": amount, "reason": "late"},
        ).id
        voucher = create_proposal(
            s,
            tid,
            case_id=case_id,
            action="free_item_voucher",
            reason="policy",
            params={
                "transaction_id": str(order_id),
                "value_paise": settings["voucher_auto_approve_max_paise"],
                "reason": "x",
            },
        ).id
    for pid in (refund, voucher):
        with tenant_session(tid, app_engine) as s:
            decide(s, hq, pid, "approved", now)
    assert execute_refund(app_engine, hq, refund).status == "succeeded"
    assert execute_voucher(app_engine, hq, voucher).status == "succeeded"
    yield {"cfg": cfg, "location_id": str(location_id), "refund_paise": amount}
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid, RefundOperation.transaction_id == order_id
            )
        )
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.id == case_id))
    reset_mocks()


def test_franchisee_numbers_equal_hq_numbers_for_the_same_locations(api, money_moved):
    cfg = money_moved["cfg"]
    hq_rows = api.get("/insights/outlets", headers=login(api, cfg.slug, _hq(cfg))).json()
    hit = next(r for r in hq_rows if r["location_id"] == money_moved["location_id"])
    # The numbers under test are real: this outlet has a case, a refund and a voucher.
    assert hit["cases_opened"] >= 1
    assert hit["refunds_confirmed_count"] >= 1
    assert hit["refunds_confirmed_paise"] >= money_moved["refund_paise"]
    assert hit["vouchers_issued_count"] >= 1 and hit["vouchers_issued_paise"] > 0
    for user in _users(cfg, "franchisee_owner"):
        headers = login(api, cfg.slug, user.email)
        own = set(api.get("/me", headers=headers).json()["location_ids"])
        rows = api.get("/insights/outlets", headers=headers).json()
        # Every field (each count and paise) matches HQ's row for the same location.
        assert rows == [r for r in hq_rows if r["location_id"] in own], user.email
