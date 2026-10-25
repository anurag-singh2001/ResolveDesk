"""make flight's invariants: confirmed only for an approved payout (staff or auto-approved)."""

from scripts.flight import Row, _check


def _row(action, opened, final, approved=False):
    return Row("t", "c@x.test", "cat", action, 100, opened, final, approved)


def _fails(row):
    failures: list[str] = []
    _check(row, failures)
    return failures


def test_auto_approved_voucher_may_be_confirmed():
    assert _fails(_row("free_item_voucher", "processing", "confirmed")) == []


def test_staff_approved_refund_may_be_confirmed():
    assert _fails(_row("refund", "awaiting_approval", "confirmed", approved=True)) == []


def test_confirmed_without_any_approval_fails():
    assert _fails(_row("refund", "awaiting_approval", "confirmed"))


def test_confirmed_with_no_payout_fails():
    assert _fails(_row(None, "escalated", "confirmed"))


def test_approved_payout_must_not_be_lost():
    assert _fails(_row("free_item_voucher", "processing", "escalated"))
