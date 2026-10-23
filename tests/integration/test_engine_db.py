"""Engine tables enforce the money/approval rules in the database itself."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.actions.base import registered_actions
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Execution,
    RefundOperation,
    Transaction,
    User,
    WorkflowRun,
)
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import TenantContext, tenant_id_for
from app.engine.approvals import check_usable
from app.engine.proposals import ProposalError, create_proposal, proposal_hash_is_intact

NOW = datetime.now(UTC)


def _ctx(tenant_id, user_id):
    return TenantContext(tenant_id, user_id, uuid.uuid4(), "hq_owner", frozenset(), frozenset())


@pytest.fixture
def case(app_engine, maint_engine, seeded_history, tenant):
    """A case on one of the tenant's orders; removed (with its engine rows) afterwards."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        order = s.scalars(select(Transaction).order_by(Transaction.id).limit(1)).one()
        other_order = s.scalars(
            select(Transaction).where(Transaction.customer_id != order.customer_id).limit(1)
        ).one()
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
            "customer_id": order.customer_id,
            "order_id": order.id,
            "other_order_id": other_order.id,
            "total": order.total_paise,
            "user_id": user_id,
        }
    yield info
    # The app role can't delete engine rows (by design); cleanup runs as the
    # maintenance role (RLS applies), and every delete also filters on tenant_id.
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid,
                RefundOperation.transaction_id == info["order_id"],
            )
        )
        s.execute(
            delete(Case).where(Case.tenant_id == tid, Case.customer_id == info["customer_id"])
        )


def _params(case, **overrides):
    return {
        "transaction_id": str(case["order_id"]),
        "amount_paise": case["total"] // 2,
        "reason": "late delivery",
    } | overrides


def _proposal(app_engine, case, **overrides):
    with tenant_session(case["tid"], app_engine) as s:
        p = create_proposal(
            s,
            _ctx(case["tid"], case["user_id"]),
            case_id=case["case_id"],
            action="refund",
            params=_params(case, **overrides),
            reason="late delivery policy",
        )
        return p.id, p.payload_hash, p.amount_paise


def _approval(case, proposal_id, digest, **overrides):
    values = dict(
        id=uuid.uuid4(),
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


def _approved(app_engine, case, **overrides):
    proposal_id, digest, amount = _proposal(app_engine, case)
    approval = _approval(case, proposal_id, digest, **overrides)
    approval_id = approval.id  # read before commit expires the instance
    with tenant_session(case["tid"], app_engine) as s:
        s.add(approval)
    return proposal_id, approval_id, amount


def _refuses(app_engine, case, row_or_stmt, error=IntegrityError, match=None):
    """The app role's attempt (an ORM row to insert, or a statement) must fail."""
    with pytest.raises(error, match=match), tenant_session(case["tid"], app_engine) as s:
        if isinstance(row_or_stmt, ActionProposal | Approval | Execution | RefundOperation):
            s.add(row_or_stmt)
            s.flush()
        else:
            s.execute(row_or_stmt)


# --- proposals -------------------------------------------------------------------------


def test_proposal_is_stored_with_an_intact_hash(app_engine, case):
    proposal_id, _, _ = _proposal(app_engine, case)
    with tenant_session(case["tid"], app_engine) as s:
        p = s.get(ActionProposal, proposal_id)
        assert proposal_hash_is_intact(p)
        assert (p.amount_paise, p.amount_param) == (case["total"] // 2, "amount_paise")
        assert p.risk == "high"


@pytest.mark.parametrize("statement", ["update", "delete"])
def test_proposals_cannot_be_changed_or_removed_by_the_app(app_engine, case, statement):
    proposal_id, _, _ = _proposal(app_engine, case)
    stmt = (
        update(ActionProposal).where(ActionProposal.id == proposal_id).values(amount_paise=1)
        if statement == "update"
        else delete(ActionProposal).where(ActionProposal.id == proposal_id)
    )
    _refuses(app_engine, case, stmt, DBAPIError, "permission denied|immutable")


def _raw_proposal(case, **overrides):
    values = dict(
        id=uuid.uuid4(),
        tenant_id=case["tid"],
        case_id=case["case_id"],
        action="refund",
        params=_params(case, amount_paise=100),
        payload_hash="a" * 64,
        amount_paise=100,
        amount_param="amount_paise",
        risk="high",
        reason="x",
    )
    return ActionProposal(**(values | overrides))


def test_amount_column_must_match_hashed_params(app_engine, case):
    _refuses(app_engine, case, _raw_proposal(case, amount_paise=99_999))


def test_tampered_hash_is_detected(app_engine, case):
    row = _raw_proposal(case, payload_hash="b" * 64)  # not the hash of these params
    row_id = row.id
    with tenant_session(case["tid"], app_engine) as s:
        s.add(row)
    with tenant_session(case["tid"], app_engine) as s:
        assert not proposal_hash_is_intact(s.get(ActionProposal, row_id))


def test_proposal_params_must_belong_to_the_case(app_engine, case):
    with pytest.raises(ProposalError, match="not this case's order"):
        _proposal(app_engine, case, transaction_id=str(case["other_order_id"]))


def test_proposal_run_must_belong_to_the_case(app_engine, case):
    with tenant_session(case["tid"], app_engine) as s:
        other_case = Case(
            id=uuid.uuid4(),
            tenant_id=case["tid"],
            customer_id=case["customer_id"],
            status="open",
            channel="app",
            opened_at=NOW,
        )
        s.add(other_case)
        s.flush()
        run = WorkflowRun(
            id=uuid.uuid4(), tenant_id=case["tid"], case_id=other_case.id, status="running"
        )
        s.add(run)
        run_id = run.id
    with pytest.raises(IntegrityError), tenant_session(case["tid"], app_engine) as s:
        create_proposal(
            s,
            _ctx(case["tid"], case["user_id"]),
            case_id=case["case_id"],
            run_id=run_id,
            action="refund",
            params=_params(case),
            reason="x",
        )


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


def test_proposal_for_another_tenants_case_is_unknown(
    app_engine, maint_engine, seeded_history, case, tenant
):
    other = next(slug for slug in seeded_history if slug != tenant.name)
    other_tid = tenant_id_for(seeded_history[other].slug)
    with tenant_session(other_tid, app_engine) as s:
        order = s.scalars(select(Transaction).limit(1)).one()
        foreign = Case(
            id=uuid.uuid4(),
            tenant_id=other_tid,
            customer_id=order.customer_id,
            status="open",
            channel="app",
            opened_at=NOW,
        )
        s.add(foreign)
        foreign_id = foreign.id
    try:
        with (
            pytest.raises(ProposalError, match="unknown case"),
            tenant_session(case["tid"], app_engine) as s,
        ):
            create_proposal(
                s,
                _ctx(case["tid"], case["user_id"]),
                case_id=foreign_id,
                action="refund",
                params=_params(case),
                reason="x",
            )
    finally:
        with tenant_session(other_tid, maint_engine) as s:
            s.execute(delete(Case).where(Case.tenant_id == other_tid, Case.id == foreign_id))


# --- approvals -------------------------------------------------------------------------


def test_approval_must_carry_the_proposals_hash(app_engine, case):
    proposal_id, _, _ = _proposal(app_engine, case)
    _refuses(app_engine, case, _approval(case, proposal_id, "f" * 64))


def test_only_one_decision_per_proposal(app_engine, case):
    proposal_id, digest, _ = _proposal(app_engine, case)
    with tenant_session(case["tid"], app_engine) as s:
        s.add(_approval(case, proposal_id, digest, decision="rejected"))
    _refuses(app_engine, case, _approval(case, proposal_id, digest))  # second manager


@pytest.mark.parametrize("statement", ["flip", "extend", "delete"])
def test_decisions_cannot_be_changed_or_removed(app_engine, case, statement):
    _, approval_id, _ = _approved(app_engine, case, decision="rejected")
    later = NOW + timedelta(days=365)
    stmt = {
        "flip": update(Approval).where(Approval.id == approval_id).values(decision="approved"),
        "extend": update(Approval).where(Approval.id == approval_id).values(expires_at=later),
        "delete": delete(Approval).where(Approval.id == approval_id),
    }[statement]
    _refuses(app_engine, case, stmt, DBAPIError, "permission denied|immutable")


@pytest.mark.parametrize(
    "overrides",
    [
        {"decided_by": None},
        {"expires_at": NOW},
        {"expires_at": NOW + timedelta(days=8)},
        {"decision": "maybe"},
        {"mode": "auto"},
    ],
    ids=["human_without_user", "no_window", "beyond_cap", "bad_decision", "auto_with_user"],
)
def test_approval_shape_is_enforced(app_engine, case, overrides):
    proposal_id, digest, _ = _proposal(app_engine, case)
    _refuses(app_engine, case, _approval(case, proposal_id, digest, **overrides))


def test_check_usable_reports_each_failure(app_engine, case):
    proposal_id, digest, _ = _proposal(app_engine, case)
    with tenant_session(case["tid"], app_engine) as s:
        proposal = s.get(ActionProposal, proposal_id)
        live = _approval(case, proposal_id, digest)
        assert check_usable(live, proposal, NOW).ok
        assert check_usable(None, proposal, NOW).reason == "no_approval"
        assert check_usable(live, proposal, live.expires_at).reason == "expired"
        rejected = _approval(case, proposal_id, digest, decision="rejected")
        assert check_usable(rejected, proposal, NOW).reason == "rejected"
        other = _approval(case, uuid.uuid4(), digest)
        assert check_usable(other, proposal, NOW).reason == "approval_for_another_proposal"
        stale = _approval(case, proposal_id, "c" * 64)
        assert check_usable(stale, proposal, NOW).reason == "payload_changed"


# --- executions + refund ledger --------------------------------------------------------


def _execution(case, proposal_id, approval_id, key=None):
    return Execution(
        tenant_id=case["tid"],
        proposal_id=proposal_id,
        approval_id=approval_id,
        idempotency_key=key or f"P-{proposal_id}:refund:1",
        status="submitted",
    )


def _reservation(case, proposal_id, amount, order_id=None, key=None):
    return RefundOperation(
        tenant_id=case["tid"],
        transaction_id=order_id or case["order_id"],
        proposal_id=proposal_id,
        idempotency_key=key or f"P-{proposal_id}:refund:1",
        amount_paise=amount,
        status="reserved",
    )


def test_execution_needs_an_approved_approval_of_the_same_proposal(app_engine, case):
    p1, a1, _ = _approved(app_engine, case)
    p2, a2_rejected, _ = _approved(app_engine, case, decision="rejected")
    _refuses(app_engine, case, _execution(case, p2, a1))  # another proposal's approval
    _refuses(app_engine, case, _execution(case, p2, a2_rejected))  # rejected approval
    with tenant_session(case["tid"], app_engine) as s:
        s.add(_execution(case, p1, a1))
    _refuses(app_engine, case, _execution(case, p1, a1, key="another-key"))  # one per proposal


def test_reservation_must_match_its_proposal(app_engine, case):
    proposal_id, _, amount = _approved(app_engine, case)
    _refuses(app_engine, case, _reservation(case, proposal_id, amount + 1))
    other_order = _reservation(case, proposal_id, amount, order_id=case["other_order_id"])
    _refuses(app_engine, case, other_order)
    with tenant_session(case["tid"], app_engine) as s:
        s.add(_reservation(case, proposal_id, amount))
    _refuses(app_engine, case, _reservation(case, proposal_id, amount, key="second-key"))


def test_execution_and_ledger_only_change_status(app_engine, case):
    proposal_id, approval_id, amount = _approved(app_engine, case)
    with tenant_session(case["tid"], app_engine) as s:
        s.add(_execution(case, proposal_id, approval_id))
        s.add(_reservation(case, proposal_id, amount))
    with tenant_session(case["tid"], app_engine) as s:  # status transitions are allowed
        s.execute(
            update(Execution)
            .where(Execution.proposal_id == proposal_id)
            .values(status="succeeded", provider_reference="rf_1")
        )
        s.execute(
            update(RefundOperation)
            .where(RefundOperation.proposal_id == proposal_id)
            .values(status="succeeded")
        )
    forbidden = [
        update(Execution).where(Execution.proposal_id == proposal_id).values(idempotency_key="x"),
        update(RefundOperation)
        .where(RefundOperation.proposal_id == proposal_id)
        .values(amount_paise=1),
        delete(RefundOperation).where(RefundOperation.proposal_id == proposal_id),
    ]
    for stmt in forbidden:
        _refuses(app_engine, case, stmt, DBAPIError, "permission denied")


@pytest.mark.parametrize("statement", ["UPDATE", "DELETE", "TRUNCATE"])
def test_audit_events_are_append_only(app_engine, case, statement):
    with tenant_session(case["tid"], app_engine) as s:
        s.add(AuditEvent(tenant_id=case["tid"], actor_type="system", event="t", entity_type="case"))
    sql = {
        "UPDATE": "UPDATE audit_events SET event = 'x'",
        "DELETE": "DELETE FROM audit_events",
        "TRUNCATE": "TRUNCATE audit_events",
    }[statement]
    _refuses(app_engine, case, text(sql), DBAPIError, "permission denied")
