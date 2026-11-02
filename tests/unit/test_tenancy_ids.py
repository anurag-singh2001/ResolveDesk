"""Pen test: `$` also matches before a trailing newline, so these patterns must not use it."""

from app.core.tenancy import SLUG_RE
from evals.scenarios import SCENARIO_ID


def test_ids_with_a_trailing_newline_are_refused():
    assert SLUG_RE.match("acme") and not SLUG_RE.match("acme\n")
    assert SCENARIO_ID.match("sr-late-001") and not SCENARIO_ID.match("sr-late-001\n")
