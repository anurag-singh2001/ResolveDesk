"""Voucher execution (E4.6), for every tenant: an approved voucher is issued exactly once via
its connector with a stable key, and the case is resolved only after the provider confirms.
The agent path is covered in test_agent_graph.py."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.models import AuditEvent, Case, Customer, Execution, Ticket, Transaction, User
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import load_context, tenant_id_for
from app.engine.approvals import decide
from app.engine.eligibility import order_facts
from app.engine.executor import ExecutionRefused
from app.engine.proposals import create_proposal
from app.engine.voucher_executor import execute_voucher, reconcile_voucher, voucher_key
from mocks.base import Chaos
from mocks.registry import get_mock, merchant_id_for, reset_mocks
from tests.helpers import login


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


@pytest.fixture
def flow(api, app_engine, maint_engine, seeded_history, tenant):
    """A demo customer's order, the pack's voucher category, and staff logins/contexts."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    customer = next(u for u in cfg.users if u.role == "customer")
    hq_email = next(u.email for u in cfg.users if u.role == "hq_owner")
    with tenant_session(tid, app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == customer.email))
        customer_id = s.scalar(select(Customer.id).where(Customer.user_id == user_id))
        order = s.scalars(
            select(Transaction)
            .where(Transaction.customer_id == customer_id)
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
        remedies = tenant_pack(s).remedies
        _, facts = order_facts(s, order.id)
        hq = load_context(s, tid, s.scalar(select(User.id).where(User.email == hq_email)))
        info = {
            "tid": tid,
            "order_id": order.id,
            "customer_id": customer_id,
            "category": next(cat for cat, rule in remedies.items() if rule == "voucher"),
            "settings": facts.settings,
            "hq_ctx": hq,
        }
    info["customer"] = login(api, cfg.slug, customer.email)
    info["hq"] = login(api, cfg.slug, hq_email)
    info["merchant"] = merchant_id_for(tid)
    yield info
    with tenant_session(tid, maint_engine) as s:
        case_ids = select(Case.id).where(Case.tenant_id == tid, Case.transaction_id == order.id)
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(case_ids)))
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.transaction_id == order.id))


def _open(api, f):
    resp = api.post(
        "/cases",
        headers=f["customer"],
        json={
            "transaction_id": str(f["order_id"]),
            "category": f["category"],
            "message": "This was not what I ordered.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _vouchers(f):
    return get_mock("vouchers").operations(f["merchant"])


def _case_status(app_engine, f, case_id):
    with tenant_session(f["tid"], app_engine) as s:
        return s.get(Case, uuid.UUID(case_id)).status


def test_auto_approved_voucher_is_issued_once_and_then_confirmed(api, app_engine, flow):
    f = flow
    opened = _open(api, f)
    assert opened["action"] == "free_item_voucher"
    # The response is built before the background task runs: approved, not yet issued.
    assert opened["stage"] == "processing" and "has been issued" not in opened["message"]
    final = api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()
    assert final["stage"] == "confirmed" and "has been issued" in final["message"]
    assert _case_status(app_engine, f, opened["id"]) == "resolved"
    (op,) = _vouchers(f)
    assert op.idempotency_key == voucher_key(uuid.UUID(opened["proposal_id"]))
    assert op.request.value_paise == opened["amount_paise"]
    assert op.request.customer_reference == str(f["customer_id"])  # from the case, not input


def test_a_timeout_is_processing_until_the_provider_confirms(api, app_engine, flow):
    f = flow
    get_mock("vouchers").set_chaos(Chaos(accept_then_timeout_rate=1.0), f["merchant"])
    opened = _open(api, f)
    mid = api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()
    assert mid["stage"] == "processing"  # issued at the provider, but nobody told us yet
    assert _case_status(app_engine, f, opened["id"]) == "executing"
    get_mock("vouchers").set_chaos(Chaos(), f["merchant"])
    url = f"/approvals/{opened['proposal_id']}/reconcile"
    assert api.post(url, headers=f["hq"]).status_code == 202
    assert api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()["stage"] == "confirmed"
    assert _case_status(app_engine, f, opened["id"]) == "resolved"
    assert len(_vouchers(f)) == 1


def test_a_declined_voucher_is_escalated_not_confirmed(api, app_engine, flow):
    f = flow
    get_mock("vouchers").set_chaos(Chaos(error_rate=1.0), f["merchant"])
    opened = _open(api, f)
    assert api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()["stage"] == "escalated"
    assert _case_status(app_engine, f, opened["id"]) == "escalated"


def _staff_voucher(app_engine, f):
    """A voucher above the auto-approve cap: it waits for a person."""
    value = f["settings"]["voucher_auto_approve_max_paise"] + 1
    assert value <= f["settings"]["voucher_max_paise"]
    with tenant_session(f["tid"], app_engine) as s:
        case = Case(
            id=uuid.uuid4(),
            tenant_id=f["tid"],
            customer_id=f["customer_id"],
            transaction_id=f["order_id"],
            category=f["category"],
            status="awaiting_approval",
            channel="app",
            opened_at=datetime.now(UTC),
        )
        s.add(case)
        s.flush()
        p = create_proposal(
            s,
            f["tid"],
            case_id=case.id,
            action="free_item_voucher",
            reason="staff review",
            params={"transaction_id": str(f["order_id"]), "value_paise": value, "reason": "x"},
        )
        return case.id, p.id


def test_staff_approval_of_a_voucher_issues_it_once(api, app_engine, flow):
    f = flow
    case_id, pid = _staff_voucher(app_engine, f)
    assert api.get(f"/cases/{case_id}", headers=f["customer"]).json()["stage"] == (
        "awaiting_approval"
    )
    assert _vouchers(f) == []
    resp = api.post(f"/approvals/{pid}/decision", headers=f["hq"], json={"decision": "approved"})
    assert resp.status_code == 200 and resp.json()["execution"] == "queued"
    assert api.get(f"/cases/{case_id}", headers=f["customer"]).json()["stage"] == "confirmed"
    assert _case_status(app_engine, f, str(case_id)) == "resolved"
    assert len(_vouchers(f)) == 1
    again = execute_voucher(app_engine, f["hq_ctx"], pid)  # a retry or the sweeper
    assert again.status == "succeeded" and len(_vouchers(f)) == 1


def test_a_rejected_or_undecided_voucher_is_never_issued(api, app_engine, flow):
    f = flow
    _, pid = _staff_voucher(app_engine, f)
    with pytest.raises(ExecutionRefused):
        execute_voucher(app_engine, f["hq_ctx"], pid)
    api.post(f"/approvals/{pid}/decision", headers=f["hq"], json={"decision": "rejected"})
    with pytest.raises(ExecutionRefused):
        execute_voucher(app_engine, f["hq_ctx"], pid)
    assert _vouchers(f) == []


def test_concurrent_workers_issue_one_voucher(app_engine, flow):
    f = flow
    _, pid = _staff_voucher(app_engine, f)
    with tenant_session(f["tid"], app_engine) as s:
        decide(s, f["hq_ctx"], pid, "approved", datetime.now(UTC))
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: execute_voucher(app_engine, f["hq_ctx"], pid), range(4)))
    assert {r.status for r in results} == {"succeeded"}
    assert len(_vouchers(f)) == 1
    with tenant_session(f["tid"], app_engine) as s:
        events = s.scalars(
            select(AuditEvent.event).where(
                AuditEvent.entity_id == pid, AuditEvent.event == "voucher.succeeded"
            )
        ).all()
    assert events == ["voucher.succeeded"]  # recorded once


def test_resume_after_expiry_sends_nothing_new(app_engine, flow):
    """Approval expired while the first request's answer was lost: ask by key, never resend."""
    f = flow
    _, pid = _staff_voucher(app_engine, f)
    now = datetime.now(UTC)
    with tenant_session(f["tid"], app_engine) as s:
        decide(s, f["hq_ctx"], pid, "approved", now)
    get_mock("vouchers").set_chaos(Chaos(timeout_rate=1.0), f["merchant"])  # nothing applied
    assert execute_voucher(app_engine, f["hq_ctx"], pid, now=now).status == "unknown"
    get_mock("vouchers").set_chaos(Chaos(), f["merchant"])
    later = now + timedelta(days=8)
    with pytest.raises(ExecutionRefused):
        reconcile_voucher(app_engine, f["hq_ctx"], pid, now=later)
    assert _vouchers(f) == []
    with tenant_session(f["tid"], app_engine) as s:
        assert s.scalar(select(Execution.status).where(Execution.proposal_id == pid)) == "unknown"
