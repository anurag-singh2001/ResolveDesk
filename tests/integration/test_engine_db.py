"""Engine tables enforce the money/approval rules in the database itself."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.actions.base import registered_actions
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Execution,
    RefundOperation,
    Transaction,
    User,
)
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext, tenant_id_for
from app.engine.proposals import ProposalError, create_proposal, proposal_hash_is_intact

NOW = datetime.now(UTC)


def _ctx(tenant_id, user_id):
    return TenantContext(tenant_id, user_id, uuid.uuid4(), "hq_owner", frozenset(), frozenset())


@pytest.fixture
def case(app_engine, seeded_history, tenant):
    """A case on one of the tenant's orders; removed (with its engine rows) afterwards."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        order = s.scalars(select(Transaction).limit(1)).one()
        user_id = s.scalar(select(User.id).where(User.email == cfg.users[0].email))
        case = Case(
            id=uuid.uuid4(),
            tenant_id=tid,
            customer_id=order.customer_id,
            transaction_id=order.id,
            status="open",
            channel="app",
            opened_at=NOW,
        )
        s.add(case)
        info = {
            "tid": tid,
            "case_id": case.id,
            "order_id": order.id,
            "total": order.total_paise,
            "user_id": user_id,
        }
    yield info
    with tenant_session(tid, app_engine) as s:
        s.execute(delete(RefundOperation).where(RefundOperation.transaction_id == info["order_id"]))
        s.execute(delete(Case).where(Case.id == info["case_id"]))


def _refund_proposal(app_engine, case, amount=None):
    with tenant_session(case["tid"], app_engine) as s:
        p = create_proposal(
            s,
            _ctx(case["tid"], case["user_id"]),
            case_id=case["case_id"],
            action="refund",
            params={
                "transaction_id": str(case["order_id"]),
                "amount_paise": amount or case["total"] // 2,
                "reason": "late delivery",
            },
            reason="late delivery policy",
        )
        return p.id, p.payload_hash


def _approval(case, proposal_id, digest, **overrides):
    values = dict(
        tenant_id=case["tid"],
        proposal_id=proposal_id,
        payload_hash=digest,
        decision="approved",
        mode="human",
        decided_by=case["user_id"],
        decided_at=NOW,
        expires_at=NOW + timedelta(hours=4),
    )
    return Approval(**(values | overrides))


def test_proposal_is_stored_with_an_intact_hash(app_engine, case):
    proposal_id, digest = _refund_proposal(app_engine, case)
    with tenant_session(case["tid"], app_engine) as s:
        p = s.get(ActionProposal, proposal_id)
        assert proposal_hash_is_intact(p)
        assert p.amount_paise == case["total"] // 2 and p.risk == "high"
        assert p.params["transaction_id"] == str(case["order_id"])


def test_proposals_are_immutable(app_engine, case):
    proposal_id, _ = _refund_proposal(app_engine, case)
    with (
        pytest.raises(DBAPIError, match="immutable"),
        tenant_session(case["tid"], app_engine) as s,
    ):
        s.execute(
            update(ActionProposal)
            .where(ActionProposal.id == proposal_id)
            .values(amount_paise=case["total"])
        )


def test_approval_must_carry_the_proposals_hash(app_engine, case):
    proposal_id, _ = _refund_proposal(app_engine, case)
    with pytest.raises(IntegrityError), tenant_session(case["tid"], app_engine) as s:
        s.add(_approval(case, proposal_id, "f" * 64))
        s.flush()


def test_only_one_decision_per_proposal(app_engine, case):
    proposal_id, digest = _refund_proposal(app_engine, case)
    with tenant_session(case["tid"], app_engine) as s:
        s.add(_approval(case, proposal_id, digest))
    with pytest.raises(IntegrityError), tenant_session(case["tid"], app_engine) as s:
        s.add(_approval(case, proposal_id, digest, decision="rejected"))  # second manager
        s.flush()


@pytest.mark.parametrize(
    "overrides",
    [{"decided_by": None}, {"expires_at": NOW}, {"decision": "maybe"}, {"mode": "auto"}],
    ids=["human_without_user", "no_expiry_window", "bad_decision", "auto_with_user"],
)
def test_approval_shape_is_enforced(app_engine, case, overrides):
    proposal_id, digest = _refund_proposal(app_engine, case)
    with pytest.raises(IntegrityError), tenant_session(case["tid"], app_engine) as s:
        s.add(_approval(case, proposal_id, digest, **overrides))
        s.flush()


def test_idempotency_keys_are_unique(app_engine, case):
    proposal_id, digest = _refund_proposal(app_engine, case)
    key = f"P-{proposal_id}:refund:1"
    with tenant_session(case["tid"], app_engine) as s:
        approval = _approval(case, proposal_id, digest)
        s.add(approval)
        s.flush()
        approval_id = approval.id
        s.add(
            Execution(
                tenant_id=case["tid"],
                proposal_id=proposal_id,
                approval_id=approval_id,
                idempotency_key=key,
                status="submitted",
            )
        )
        s.add(
            RefundOperation(
                tenant_id=case["tid"],
                transaction_id=case["order_id"],
                proposal_id=proposal_id,
                idempotency_key=key,
                amount_paise=100,
                status="reserved",
            )
        )
    for row in (
        Execution(
            tenant_id=case["tid"],
            proposal_id=proposal_id,
            approval_id=approval_id,
            idempotency_key=key,
            status="submitted",
        ),
        RefundOperation(
            tenant_id=case["tid"],
            transaction_id=case["order_id"],
            proposal_id=proposal_id,
            idempotency_key=key,
            amount_paise=100,
            status="reserved",
        ),
    ):
        with pytest.raises(IntegrityError), tenant_session(case["tid"], app_engine) as s:
            s.add(row)
            s.flush()


def test_refund_ledger_rejects_non_positive_amounts(app_engine, case):
    proposal_id, _ = _refund_proposal(app_engine, case)
    with pytest.raises(IntegrityError), tenant_session(case["tid"], app_engine) as s:
        s.add(
            RefundOperation(
                tenant_id=case["tid"],
                transaction_id=case["order_id"],
                proposal_id=proposal_id,
                idempotency_key="k",
                amount_paise=0,
                status="reserved",
            )
        )
        s.flush()


def test_action_outside_the_tenants_pack_is_refused(app_engine, case):
    with tenant_session(case["tid"], app_engine) as s:
        missing = sorted(set(registered_actions()) - set(tenant_pack(s).actions))
    if not missing:
        pytest.skip("this tenant's pack enables every registered action")
    with (
        pytest.raises(ProposalError, match="not enabled"),
        tenant_session(case["tid"], app_engine) as s,
    ):
        create_proposal(
            s,
            _ctx(case["tid"], case["user_id"]),
            case_id=case["case_id"],
            action=missing[0],
            params={},
            reason="x",
        )


def test_proposal_cannot_point_at_another_tenants_case(app_engine, seeded_history, case, tenant):
    other = next(slug for slug in seeded_history if slug != tenant.name)
    other_tid = tenant_id_for(seeded_history[other].slug)
    with tenant_session(other_tid, app_engine) as s:
        foreign_case = s.scalar(select(Case.id).limit(1))
        if foreign_case is None:
            order = s.scalars(select(Transaction).limit(1)).one()
            foreign_case = uuid.uuid4()
            s.add(
                Case(
                    id=foreign_case,
                    tenant_id=other_tid,
                    customer_id=order.customer_id,
                    status="open",
                    channel="app",
                    opened_at=NOW,
                )
            )
    try:
        with pytest.raises(IntegrityError), tenant_session(case["tid"], app_engine) as s:
            create_proposal(
                s,
                _ctx(case["tid"], case["user_id"]),
                case_id=foreign_case,
                action="refund",
                params={
                    "transaction_id": str(case["order_id"]),
                    "amount_paise": 100,
                    "reason": "x",
                },
                reason="x",
            )
    finally:
        with tenant_session(other_tid, app_engine) as s:
            s.execute(delete(Case).where(Case.id == foreign_case))
