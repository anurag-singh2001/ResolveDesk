# ruff: noqa: F811
"""S8.9: a voucher proposed before S7.8 can still be pending with a value above its order's total
(a Rs 150 voucher on a Rs 149 order). Approving it must fail safely with a plain reason, nothing
may be issued, and the approvals list must tell the approver why. Runs for every tenant."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.db import tenant_session
from app.core.models import Approval, Case, Transaction
from app.engine.proposals import create_proposal
from tests.integration.test_voucher_execution import _vouchers, flow  # noqa: F401


def _set_total(maint_engine, f, total):
    with tenant_session(f["tid"], maint_engine) as s:
        old = s.scalar(select(Transaction.total_paise).where(Transaction.id == f["order_id"]))
        s.execute(
            update(Transaction).where(Transaction.id == f["order_id"]).values(total_paise=total)
        )
    return old


def _pending_voucher(app_engine, f, value):
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
        return p.id


def test_a_pending_voucher_above_the_order_total_cannot_be_approved(
    api, app_engine, maint_engine, flow
):
    f = flow
    total = f["settings"]["voucher_max_paise"] - 100  # the pending value stays within the cap
    value = total + 100
    assert total > 0
    old = _set_total(maint_engine, f, total)
    try:
        pid = _pending_voucher(app_engine, f, value)
        rows = api.get("/approvals?limit=500", headers=f["hq"]).json()
        row = next(r for r in rows if r["proposal_id"] == str(pid))
        assert row["eligible"] is False
        assert row["checks"]["order_total_paise"] == total and row["amount_paise"] == value
        assert any("paid for the order" in e for e in row["errors"])

        resp = api.post(
            f"/approvals/{pid}/decision", headers=f["hq"], json={"decision": "approved"}
        )
        assert resp.status_code == 422, resp.text  # a plain reason, not a 500
        assert any("paid for the order" in e for e in resp.json()["detail"])
        with tenant_session(f["tid"], app_engine) as s:
            assert s.scalar(select(Approval.id).where(Approval.proposal_id == pid)) is None
        assert _vouchers(f) == []

        # Rejecting stays possible: the approver is never stuck with it.
        rej = api.post(f"/approvals/{pid}/decision", headers=f["hq"], json={"decision": "rejected"})
        assert rej.status_code == 200, rej.text
    finally:
        _set_total(maint_engine, f, old)
