"""Operator release of quarantined refunds (E4.4), for every tenant.

Done-when: release never frees money the provider later applies (tested with a late landing).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.models import AuditEvent, Execution
from app.engine.eligibility import refundable_paise
from app.engine.executor import ExecutionRefused, execute_refund
from app.engine.release import RELEASE_MARGIN, release_refund
from mocks.base import Chaos
from mocks.registry import get_mock
from tests.helpers import login
from tests.integration.test_refund_executor import (  # noqa: F401 (fixtures)
    NOW,
    approve,
    clean_mocks,
    ledger,
    propose,
    provider_ops,
    small,
    world,
)

LIFETIME = timedelta(seconds=get_mock("payment").request_lifetime_s)


class Clock:
    """The mock provider's clock, moved by the test."""

    def __init__(self) -> None:
        self.t = NOW.timestamp()

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: timedelta) -> None:
        self.t += delta.total_seconds()


def _expiry(w) -> timedelta:
    return timedelta(minutes=w["settings"]["approval_expiry_minutes"])


@pytest.fixture
def quarantined(app_engine, world, request):  # noqa: F811
    """A refund whose request timed out while still in flight (it lands `land_after` later,
    or never if that is past the provider's request lifetime); the approval then expired and
    the resume quarantined it. Returns (world, proposal id, provider clock)."""
    w = world
    clock = Clock()
    pay = get_mock("payment")
    pay.set_clock(clock)
    pay.set_chaos(Chaos(land_late_rate=1.0, land_after_s=request.param.total_seconds()))
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    assert execute_refund(app_engine, w["hq"], pid, now=NOW).status == "unknown"
    pay.set_chaos(Chaos())
    after_expiry = NOW + _expiry(w) + timedelta(seconds=1)
    with pytest.raises(ExecutionRefused):
        execute_refund(app_engine, w["hq"], pid, now=after_expiry)
    assert [r.status for r in ledger(app_engine, w)] == ["pending_reconciliation"]
    return w, pid, clock


def _ready(w) -> datetime:
    # Approval expiry dominates the ledger's last change here; then lifetime + margin.
    return NOW + _expiry(w) + LIFETIME + RELEASE_MARGIN + timedelta(seconds=5)


def _balance(app_engine, w):
    with tenant_session(w["tid"], app_engine) as s:
        return refundable_paise(s, w["order_id"])


@pytest.mark.parametrize("quarantined", [LIFETIME / 2], indirect=True, ids=["lands_late"])
def test_a_late_landing_is_recorded_never_released(app_engine, quarantined):
    w, pid, clock = quarantined
    held = _balance(app_engine, w)
    early = release_refund(app_engine, w["hq"], pid, now=_ready(w) - timedelta(minutes=2))
    assert (early.outcome, early.reason) == ("refused", "too_early")
    clock.advance(LIFETIME)  # the in-flight request lands at the provider
    result = release_refund(app_engine, w["hq"], pid, now=_ready(w))
    assert result.outcome == "recorded" and result.status == "succeeded"
    assert [r.status for r in ledger(app_engine, w)] == ["succeeded"]
    assert _balance(app_engine, w) == held  # nothing freed
    assert len(provider_ops(w)) == 1
    again = release_refund(app_engine, w["hq"], pid, now=_ready(w))
    assert (again.outcome, again.reason) == ("refused", "not_held")


@pytest.mark.parametrize("quarantined", [LIFETIME * 3], indirect=True, ids=["never_lands"])
def test_release_after_the_window_frees_the_balance_and_nothing_lands_later(
    app_engine, quarantined
):
    w, pid, clock = quarantined
    held = _balance(app_engine, w)
    clock.advance(LIFETIME + timedelta(seconds=1))  # past the request lifetime
    result = release_refund(app_engine, w["hq"], pid, now=_ready(w))
    assert (result.outcome, result.status) == ("released", "released")
    assert [r.status for r in ledger(app_engine, w)] == ["released"]
    assert _balance(app_engine, w) == held + small(w)
    clock.advance(LIFETIME * 10)
    assert get_mock("payment").get_refund("m_" + w["tid"].hex, f"P-{pid}:refund:1") is None
    assert provider_ops(w) == []  # the provider contract: it can never land now
    with tenant_session(w["tid"], app_engine) as s:
        execution = s.scalar(select(Execution).where(Execution.proposal_id == pid))
        assert execution.status == "failed" and execution.error.startswith("released")
        events = s.execute(
            select(AuditEvent.actor_type, AuditEvent.actor_id).where(
                AuditEvent.entity_id == pid, AuditEvent.event == "refund.released"
            )
        ).all()
    assert [(t, str(a)) for t, a in events] == [("user", str(w["hq"].user_id))]


@pytest.mark.parametrize("quarantined", [LIFETIME * 3], indirect=True, ids=["never_lands"])
def test_release_is_refused_while_the_provider_cannot_answer(app_engine, quarantined, monkeypatch):
    from app.connectors.base import RefundOutcome
    from app.connectors.mock_connectors import MockPaymentConnector

    w, pid, _ = quarantined
    monkeypatch.setattr(
        MockPaymentConnector, "find_refund", lambda self, ctx, key: RefundOutcome("unavailable")
    )
    result = release_refund(app_engine, w["hq"], pid, now=_ready(w))
    assert (result.outcome, result.reason) == ("refused", "provider_unavailable")
    assert [r.status for r in ledger(app_engine, w)] == ["pending_reconciliation"]


def test_a_reserved_refund_with_a_usable_approval_is_not_released(app_engine, world):  # noqa: F811
    """Reserved and never sent, but still executable: the sweeper finishes it instead."""
    from app.engine.executor import _reserve

    w = world
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid)
    _reserve(app_engine, w["hq"], pid, NOW)
    result = release_refund(app_engine, w["hq"], pid, now=NOW + timedelta(minutes=1))
    assert (result.outcome, result.reason) == ("refused", "still_executable")
    later = NOW + _expiry(w) + LIFETIME + RELEASE_MARGIN + timedelta(seconds=5)
    assert release_refund(app_engine, w["hq"], pid, now=later).outcome == "released"
    assert [r.status for r in ledger(app_engine, w)] == ["released"]


def test_only_an_hq_owner_can_release_and_never_too_early(api, app_engine, world):  # noqa: F811
    w = world
    past = datetime.now(UTC) - _expiry(w) - timedelta(minutes=1)  # the API uses real time
    pid = propose(app_engine, w, small(w))
    approve(app_engine, w, pid, now=past)
    get_mock("payment").set_chaos(Chaos(timeout_rate=1.0))
    execute_refund(app_engine, w["hq"], pid, now=past)
    with pytest.raises(ExecutionRefused):  # quarantined: the approval has expired by now
        execute_refund(app_engine, w["hq"], pid)
    slug = w["cfg"].slug
    url = f"/approvals/{pid}/release"
    others = [u for u in w["cfg"].users if u.role != "hq_owner"]
    assert others
    for user in others:
        assert api.post(url, headers=login(api, slug, user.email)).status_code == 403
    hq = login(api, slug, next(u.email for u in w["cfg"].users if u.role == "hq_owner"))
    resp = api.post(url, headers=hq)  # the ledger changed just now: the window hasn't passed
    assert resp.status_code == 409 and resp.json()["detail"]["reason"] == "too_early"
    assert api.post(f"/approvals/{uuid.uuid4()}/release", headers=hq).status_code == 404
    assert [r.status for r in ledger(app_engine, w)] == ["pending_reconciliation"]
