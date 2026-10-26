"""Voucher timeline steps follow the execution, like case_status: issued only on success."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.engine.case_timeline import _voucher_steps

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


class _Session:
    def __init__(self, execution):
        self.execution = execution

    def scalar(self, _query):
        return self.execution


def _steps(execution, expires_at=NOW + timedelta(hours=1)):
    proposal = SimpleNamespace(id="p", amount_paise=10_000)
    approval = SimpleNamespace(expires_at=expires_at)
    return _voucher_steps(_Session(execution), proposal, approval, NOW)


def _execution(status):
    return SimpleNamespace(status=status, updated_at=NOW)


def test_issued_only_when_the_provider_confirmed():
    (step,) = _steps(_execution("succeeded"))
    assert (step.stage, step.title) == ("confirmed", "Voucher issued")
    assert "₹100.00" in step.text


def test_a_failed_voucher_is_passed_to_the_team():
    (step,) = _steps(_execution("failed"))
    assert step.stage == "escalated" and "could not issue" in step.text


def test_an_approval_that_lapsed_unexecuted_needs_a_check():
    (step,) = _steps(None, expires_at=NOW - timedelta(minutes=1))
    assert step.stage == "escalated"


def test_in_flight_or_waiting_adds_no_step():
    assert _steps(_execution("unknown")) == []
    assert _steps(_execution("submitted")) == []
    assert _steps(None) == []
