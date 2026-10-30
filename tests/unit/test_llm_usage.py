"""Per-model usage counters on RunBudget and the cost estimate (S9.2): fake providers, no DB."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import Settings
from app.core.telemetry import _outcome, estimate_cost_micro_paise
from app.llm.providers import LLMClient, RunBudget, Target

SECRET = "my phone is 9876543210 and I live at 12 Hidden Lane"


class Fake(BaseChatModel):
    fail: bool = False
    reply: str = "Sure, sorted. 9876543210"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.fail:
            raise RuntimeError(f"boom {SECRET}")
        msg = AIMessage(
            content=self.reply,
            usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


def make(primary, fallback=None, role="main"):
    s = Settings(_env_file=None, app_env="test", llm_retry_attempts=0)
    budget = RunBudget.from_settings(s)
    c = LLMClient(
        Target("p", "p-model", primary),
        Target("f", "f-model", fallback) if fallback else None,
        budget=budget,
        settings=s,
        role=role,
    )
    return c, budget


def test_each_provider_request_is_counted_per_role_provider_model():
    c, budget = make(Fake(), role="classifier")
    c.invoke([("human", SECRET)])
    c.invoke([("human", SECRET)])
    (row,) = budget.take_usage()
    assert (row["role"], row["provider"], row["model"]) == ("classifier", "p", "p-model")
    assert (row["calls"], row["input_tokens"], row["output_tokens"]) == (2, 200, 80)
    assert row["failures"] == 0 and row["fallback"] is False
    assert isinstance(row["latency_ms"], int) and row["latency_ms"] >= 0
    assert budget.take_usage() == []  # taken once: a second recording cannot double count


def test_failure_then_fallback_is_two_rows_with_class_name_only():
    c, budget = make(Fake(fail=True), Fake())
    c.invoke([("human", SECRET)])
    rows = {r["provider"]: r for r in budget.take_usage()}
    assert rows["p"]["failures"] == 1 and rows["p"]["error_class"] == "RuntimeError"
    assert rows["f"]["fallback"] is True and rows["f"]["input_tokens"] == 100
    assert _outcome(rows["p"]) == "error"
    assert _outcome(rows["f"]) == "fallback_used"
    # numbers and class names only: neither the prompt nor the exception text is kept
    assert SECRET not in repr(rows) and "9876543210" not in repr(rows)


def test_usage_is_not_in_the_snapshot_the_run_returns():
    c, budget = make(Fake())
    c.invoke([("human", "hi")])
    assert "_usage" not in budget.snapshot()


def test_cost_is_integer_micro_paise_from_the_price_table():
    s = Settings(
        _env_file=None,
        app_env="test",
        llm_prices_paise_per_million={"p/p-model": (25, 100)},
    )
    cost = estimate_cost_micro_paise(s, "p", "p-model", 1_000, 500)
    assert cost == 1_000 * 25 + 500 * 100 and isinstance(cost, int)
    assert estimate_cost_micro_paise(s, "p", "unlisted", 1_000, 500) == 0


def test_price_table_rejects_floats_and_negatives():
    import pytest
    from pydantic import ValidationError

    for bad in ({"a/b": (1.5, 2)}, {"a/b": (-1, 2)}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, llm_prices_paise_per_million=bad)
