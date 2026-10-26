"""LLM factory behaviour with fake chat models: no network, no DB."""

import json

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from app.config import Settings
from app.llm.providers import (
    BudgetExceeded,
    LLMClient,
    MissingAPIKey,
    ProviderFailed,
    RateLimited,
    ResponseCache,
    RunBudget,
    StructuredOutputError,
    Target,
    get_chat_model,
    is_rate_limit,
    model_name,
)


class Classification(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)
    needs_info: list[str]


VALID = json.dumps({"category": "late_delivery", "confidence": 0.9, "needs_info": []})
MSGS = [("human", "My order arrived an hour late.")]


class FakeRateLimit(Exception):
    status_code = 429


class ScriptedModel(BaseChatModel):
    """Raises the scripted exceptions in order, then replies; counts provider calls."""

    errors: list[Exception] = []
    reply: str = VALID
    calls: int = 0
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        self.seen.append(messages)
        if self.errors:
            raise self.errors.pop(0)
        msg = AIMessage(
            content=self.reply,
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


def replies(*texts: str) -> GenericFakeChatModel:
    """A fake model that can answer exactly len(texts) times."""
    return GenericFakeChatModel(messages=iter(AIMessage(content=t) for t in texts))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        llm_retry_attempts=2,
        llm_retry_base_seconds=1.0,
        llm_retry_max_seconds=1.5,
        llm_max_calls_per_run=8,
    )


def client(settings, primary, fallback=None, cache=None, budget=None):
    sleeps: list[float] = []
    c = LLMClient(
        Target("p", "p-model", primary),
        Target("f", "f-model", fallback) if fallback else None,
        budget=budget or RunBudget.from_settings(settings),
        settings=settings,
        cache=cache,
        sleep=sleeps.append,
    )
    return c, sleeps


def test_rate_limit_retries_with_backoff_then_falls_back(settings):
    primary = ScriptedModel(errors=[FakeRateLimit("slow down")] * 3)
    c, sleeps = client(settings, primary, fallback=replies(VALID))

    out = c.invoke_structured(MSGS, Classification)

    assert out.category == "late_delivery"
    assert primary.calls == 3  # first try + 2 retries
    assert sleeps == [1.0, 1.5]  # 1 * 2**0, then 1 * 2**1 capped at max
    assert (c.budget.calls, c.budget.retries, c.budget.fallbacks) == (1, 2, 1)


def test_rate_limit_recovers_on_retry_without_fallback(settings):
    primary = ScriptedModel(errors=[FakeRateLimit("429 Too Many Requests")])
    c, sleeps = client(settings, primary, fallback=replies())

    assert c.invoke_structured(MSGS, Classification).confidence == 0.9
    assert sleeps == [1.0]
    assert c.budget.fallbacks == 0
    assert (c.budget.input_tokens, c.budget.output_tokens) == (10, 5)


def test_all_providers_rate_limited_raises(settings):
    c, _ = client(
        settings,
        ScriptedModel(errors=[FakeRateLimit()] * 3),
        fallback=ScriptedModel(errors=[FakeRateLimit()] * 3),
    )
    with pytest.raises(RateLimited):
        c.invoke(MSGS)


def test_other_errors_skip_retries_and_fall_back(settings):
    primary = ScriptedModel(errors=[ValueError("bad request")])
    c, sleeps = client(settings, primary, fallback=replies(VALID))

    assert c.invoke(MSGS).content == VALID
    assert primary.calls == 1 and sleeps == [] and c.budget.fallbacks == 1


def test_all_providers_failing_raises_without_their_messages(settings):
    primary = ScriptedModel(errors=[ValueError("key=sk-secret in url")])
    fallback = ScriptedModel(errors=[RuntimeError("upstream 503 key=sk-secret")])
    c, _ = client(settings, primary, fallback=fallback)

    with pytest.raises(ProviderFailed) as exc:
        c.invoke(MSGS)
    assert "sk-secret" not in str(exc.value) and "ValueError" in str(exc.value)


def test_budget_errors_never_fall_back(settings):
    settings = settings.model_copy(update={"llm_max_provider_requests_per_run": 1})
    primary = ScriptedModel(errors=[FakeRateLimit("rate limit")])
    fallback = ScriptedModel()
    c, _ = client(settings, primary, fallback=fallback)

    with pytest.raises(BudgetExceeded):
        c.invoke(MSGS)
    assert fallback.calls == 0


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class HttpError(Exception):
    def __init__(self, msg: str = "", *, status: int | None = None, code: int | None = None):
        super().__init__(msg)
        self.response = FakeResponse(status) if status is not None else None
        self.code = code


@pytest.mark.parametrize(
    "exc",
    [
        FakeRateLimit(),  # status_code attribute
        HttpError("boom", status=429),  # response.status_code
        HttpError("boom", code=429),  # google-style `code`
        Exception("Rate limit reached for model"),
        Exception("429 RESOURCE_EXHAUSTED: quota"),
        Exception("Too Many Requests"),
    ],
)
def test_rate_limit_detection_true_positives(exc):
    assert is_rate_limit(exc)


@pytest.mark.parametrize(
    "exc",
    [
        Exception("invalid api request"),
        Exception("connection refused: localhost:4291"),  # a port containing 429
        Exception("bad request, request_id=req_4290a1"),  # a request id containing 429
        Exception("Error code: 429"),  # a bare number is not enough without a status
        HttpError("rate limit text, but HTTP 500", status=500),  # a status code decides first
    ],
)
def test_rate_limit_detection_ignores_bare_429_text(exc):
    assert not is_rate_limit(exc)


def test_repair_succeeds_on_second_try(settings):
    c, _ = client(settings, replies('{"category": "late_delivery"}', f"```json\n{VALID}\n```"))

    out = c.invoke_structured(MSGS, Classification)

    assert out.needs_info == []
    assert (c.budget.calls, c.budget.repairs) == (2, 1)


def test_repair_sends_validation_error_back(settings):
    model = ScriptedModel(reply="not json")
    c, _ = client(settings, model)

    with pytest.raises(StructuredOutputError) as err:
        c.invoke_structured(MSGS, Classification)

    assert len(model.seen) == 2  # exactly one repair attempt
    repair = model.seen[1]
    assert "not valid" in repair[-1].content and repair[-2].content == "not json"
    assert err.value.schema == "Classification" and err.value.raw == "not json"


def test_repair_failure_raises_typed_error(settings):
    c, _ = client(settings, replies('{"category": 1}', '{"confidence": 7}'))

    with pytest.raises(StructuredOutputError):
        c.invoke_structured(MSGS, Classification)
    assert c.budget.calls == 2


def test_cache_hit_avoids_second_model_call(settings, tmp_path):
    cache = ResponseCache(tmp_path)
    first, _ = client(settings, replies(VALID), cache=cache)
    assert first.invoke_structured(MSGS, Classification).category == "late_delivery"

    # This fake has no replies left: any real call would fail.
    second, _ = client(settings, replies(), cache=cache)
    assert second.invoke_structured(MSGS, Classification).category == "late_delivery"
    assert second.budget.cache_hits == 1
    assert second.budget.calls == 1  # cache hits still count toward the run limit


def test_cache_key_depends_on_provider_model_messages_and_schema():
    m = [HumanMessage(content="hi")]
    variants = [
        ("p", "m", m, "S"),
        ("q", "m", m, "S"),
        ("p", "n", m, "S"),
        ("p", "m", [HumanMessage(content="ho")], "S"),
        ("p", "m", m, "T"),
    ]
    assert ResponseCache.key(*variants[0]) == ResponseCache.key("p", "m", list(m), "S")
    assert len({ResponseCache.key(*v) for v in variants}) == len(variants)


def test_budget_exceeded_raises(settings):
    budget = RunBudget(max_calls=2)
    c, _ = client(settings, replies("a", "b", "c"), budget=budget)
    c.invoke(MSGS)
    c.invoke(MSGS)

    with pytest.raises(BudgetExceeded):
        c.invoke(MSGS)
    assert budget.snapshot()["calls"] == 2


def test_budget_default_comes_from_settings(settings):
    budget = RunBudget.from_settings(settings)
    assert budget.max_calls == settings.llm_max_calls_per_run
    assert budget.max_provider_requests == settings.llm_max_provider_requests_per_run
    assert Settings(_env_file=None, app_env="test").llm_max_provider_requests_per_run == 24


def test_provider_requests_count_retries_and_fallbacks(settings):
    primary = ScriptedModel(errors=[FakeRateLimit()] * 3)
    c, _ = client(settings, primary, fallback=replies(VALID))

    c.invoke(MSGS)

    # one logical call; 3 requests to the primary (try + 2 retries) + 1 to the fallback
    assert (c.budget.calls, c.budget.provider_requests) == (1, 4)


def test_cache_hit_sends_no_provider_request(settings, tmp_path):
    cache = ResponseCache(tmp_path)
    client(settings, replies(VALID), cache=cache)[0].invoke(MSGS)
    second, _ = client(settings, replies(), cache=cache)
    second.invoke(MSGS)
    assert (second.budget.calls, second.budget.provider_requests) == (1, 0)


def test_provider_request_cap_stops_a_retry_storm(settings):
    budget = RunBudget(max_calls=8, max_provider_requests=2)
    primary = ScriptedModel(errors=[FakeRateLimit()] * 3)
    fallback = ScriptedModel()
    c, _ = client(settings, primary, fallback=fallback, budget=budget)

    with pytest.raises(BudgetExceeded, match="provider requests"):
        c.invoke(MSGS)
    assert primary.calls == 2 and fallback.calls == 0  # the third request was never sent
    assert budget.snapshot()["provider_requests"] == 2 and budget.calls == 1


@pytest.mark.parametrize(
    ("provider", "env_var"), [("gemini", "GEMINI_API_KEY"), ("groq", "GROQ_API_KEY")]
)
def test_missing_key_error_names_env_var(monkeypatch, provider, env_var):
    monkeypatch.delenv(env_var, raising=False)
    s = Settings(_env_file=None, app_env="test", gemini_api_key=None, groq_api_key=None)

    with pytest.raises(MissingAPIKey, match=env_var):
        get_chat_model("main", provider, settings=s)


def test_model_names_come_from_settings():
    s = Settings(
        _env_file=None,
        app_env="test",
        groq_api_key="test-key",
        llm_classifier_provider="groq",
        llm_classifier_model_groq="custom-small",
    )
    chat = get_chat_model("classifier", settings=s)

    assert chat.model_name == "custom-small"
    assert model_name("main", "ollama", s) == s.llm_ollama_model
    assert "test-key" not in repr(chat)


def test_for_role_skips_fallback_without_key(monkeypatch):
    s = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="ollama",
        llm_fallback_provider="gemini",
        gemini_api_key=None,
    )
    c = LLMClient.for_role("main", settings=s)

    assert [t.provider for t in c.targets] == ["ollama"]
    assert c.cache is None
