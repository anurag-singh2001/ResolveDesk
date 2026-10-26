"""Eval scoring is plain code: the same result always gets the same score."""

from evals.harness import Ceiling, Result
from evals.metrics import cost_paise, failure_line, score, summarize
from evals.scenarios import Scenario


def _scenario(kind="plain", **expect):
    return Scenario(
        id="x-1",
        tenant="t",
        kind=kind,
        message="m",
        order={"select": "latest"},
        expect={"category": "c", "outcome": "proposed", "action": "refund", "amount": "exact"}
        | expect,
    )


def _result(sc, **kw):
    base = dict(
        pipeline="agents",
        order_id="o",
        ceiling=Ceiling("refund", 5_000),
        outcome="proposed",
        category="c",
        action="refund",
        amount=5_000,
        llm={"calls": 2, "input_tokens": 1_000_000, "output_tokens": 0},
        seconds=1.0,
    )
    return Result(sc, **(base | kw))


def test_exact_proposal_passes():
    s = score(_result(_scenario()))
    assert s.passed and s.amount_exact and s.amount_within and not s.over_ceiling


def test_less_than_the_rule_is_within_but_not_exact():
    s = score(_result(_scenario(), amount=4_000))
    assert s.amount_within and not s.amount_exact and not s.passed
    assert score(_result(_scenario(amount="within"), amount=4_000)).passed


def test_above_the_rule_or_another_action_is_over_ceiling():
    assert score(_result(_scenario(), amount=5_001)).over_ceiling
    other = _result(_scenario(), action="free_item_voucher", amount=100)
    assert score(other).over_ceiling and not score(other).passed


def test_injection_held_only_without_extra_action():
    sc = _scenario(kind="injection", outcome="escalated", action=None, amount=None)
    held = _result(sc, outcome="escalated", action=None, amount=None)
    assert score(held).injection_held and score(held).passed
    assert score(_result(sc)).injection_held is False  # refund where none was due
    assert score(_result(_scenario())).injection_held is None


def test_summary_counts_escalation_precision_and_recall():
    esc = _scenario(outcome="escalated", action=None, amount=None)
    rows = [
        _result(esc, outcome="escalated", action=None, amount=None),  # true positive
        _result(_scenario(), outcome="escalated", action=None, amount=None),  # false positive
        _result(esc),  # missed escalation
    ]
    m = summarize(rows, "openai/gpt-oss-120b")
    assert m["esc_prec"] == "50%" and m["esc_recall"] == "50%"
    assert m["cases"] == "3" and m["llm_calls"] == "2.0"
    assert failure_line(rows[0]) is None and "expected" in failure_line(rows[1])


def test_cost_is_integer_paise():
    sc = _scenario()
    cost = cost_paise([_result(sc)], "openai/gpt-oss-120b")
    assert isinstance(cost, int) and cost == 1_260  # 1M input tokens at the assumed price
    assert cost_paise([_result(sc)], "unknown-model") == 0


def test_an_auto_approved_proposal_that_ran_on_still_counts_as_proposed():
    for ran_on in ("resolved", "processing"):
        assert score(_result(_scenario(), outcome=ran_on)).passed
    esc = _scenario(outcome="escalated", action=None, amount=None)
    assert not score(_result(esc, outcome="resolved", action=None, amount=None)).outcome_ok
