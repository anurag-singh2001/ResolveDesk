"""Refund timeline steps agree with case_status after verification (S12.5, hard rule 7)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.engine.case_timeline import _refund_steps

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
PROPOSAL = SimpleNamespace(amount_paise=25_000)
APPROVAL = SimpleNamespace(expires_at=NOW + timedelta(hours=1))
LANGS = ["en", "hi-Latn", "hi"]


def _exec(status):
    return SimpleNamespace(status=status, updated_at=NOW)


def _steps(execution, verification, lang="en", ledger=None):
    return _refund_steps(PROPOSAL, APPROVAL, execution, ledger, verification, NOW, lang)


@pytest.mark.parametrize("lang", LANGS)
def test_mismatch_after_success_is_a_check_not_confirmed(lang):
    """The sequence behind O0003646: executed ok, verifier: provider has no record."""
    (step,) = _steps(_exec("succeeded"), "mismatch", lang)
    assert step.stage == "escalated"
    assert step.title != _steps(_exec("succeeded"), "verified", lang)[0].title


def test_mismatch_never_says_confirmed_or_failed():
    for ex in ("succeeded", "failed"):
        (step,) = _steps(_exec(ex), "mismatch")
        assert "needs a check" in step.text
        assert "confirmed" not in (step.title + step.text).lower()
        assert "could not" not in step.text


def test_confirmed_needs_provider_success_and_verification():
    (step,) = _steps(_exec("succeeded"), "verified")
    assert (step.stage, step.title) == ("confirmed", "Refund confirmed")
    assert _steps(_exec("succeeded"), None) == []  # still processing
    assert _steps(_exec("succeeded"), "unknown") == []


def test_unverified_failure_is_unknown_and_verified_failure_is_failed():
    (unsure,) = _steps(_exec("failed"), None)
    assert "needs a check" in unsure.text
    (failed,) = _steps(_exec("failed"), "verified")
    assert "needs a check" not in failed.text and failed.stage == "escalated"


def test_in_flight_adds_no_step():
    assert _steps(_exec("submitted"), None) == []
    assert _steps(None, None) == []
