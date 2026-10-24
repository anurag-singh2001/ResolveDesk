"""LLM provider factory, rate-limit fallback, structured output and dev cache (PROJECT.md 4, 8).

Providers and model names come from settings only. `LLMClient` is the one way agents call a
model: it counts every call against the run's `RunBudget`, backs off on rate limits and then
switches to the fallback provider, and validates structured replies with one repair attempt.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import MessageLikeRepresentation, convert_to_messages
from pydantic import BaseModel, ValidationError

from app.config import Provider, Settings, get_settings

Role = Literal["main", "classifier"]
log = logging.getLogger(__name__)

_KEY_ENV = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}


class LLMError(RuntimeError):
    pass


class MissingAPIKey(LLMError):
    def __init__(self, provider: str):
        self.env_var = _KEY_ENV[provider]
        super().__init__(f"{self.env_var} is not set; it is needed for LLM provider {provider!r}")


class RateLimited(LLMError):
    """Every provider tried was still rate limited after its retries."""


class BudgetExceeded(LLMError):
    """The run hit its LLM call limit: the engine stops and escalates."""


class StructuredOutputError(LLMError):
    def __init__(self, schema: str, error: str, raw: str):
        self.schema, self.error, self.raw = schema, error, raw
        super().__init__(f"model output is not a valid {schema} after one repair: {error}")


def model_name(role: Role, provider: Provider, settings: Settings) -> str:
    if provider == "ollama":
        return settings.llm_ollama_model
    return getattr(settings, f"llm_{role}_model_{provider}")


def get_chat_model(
    role: Role, provider: Provider | None = None, settings: Settings | None = None
) -> BaseChatModel:
    """A LangChain chat model for this role; `provider` defaults to the role's configured one."""
    s = settings or get_settings()
    provider = provider or (s.llm_provider if role == "main" else s.llm_classifier_provider)
    name = model_name(role, provider, s)
    # Provider SDK retries are off (max_retries=0) so LLMClient's backoff is the only one.
    if provider == "gemini":
        if not s.gemini_api_key:
            raise MissingAPIKey(provider)
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=name,
            google_api_key=s.gemini_api_key,
            temperature=s.llm_temperature,
            max_retries=0,
        )
    if provider == "groq":
        if not s.groq_api_key:
            raise MissingAPIKey(provider)
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=name, api_key=s.groq_api_key, temperature=s.llm_temperature, max_retries=0
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=name, base_url=s.ollama_base_url, temperature=s.llm_temperature)
    raise ValueError(f"unknown LLM provider {provider!r}")


def is_rate_limit(exc: BaseException) -> bool:
    """Generic 429 detection: provider SDKs use different exception types for the same thing."""
    response = getattr(exc, "response", None)
    for status in (getattr(exc, "status_code", None), getattr(response, "status_code", None)):
        if status == 429:
            return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(t in text for t in ("429", "rate limit", "ratelimit", "resource_exhausted"))


@dataclass
class RunBudget:
    """Per-run LLM counters. `calls` counts logical calls (incl. repairs and cache hits) so a run
    routes the same with or without the dev cache; tokens count real provider calls only."""

    max_calls: int
    calls: int = 0
    retries: int = 0
    fallbacks: int = 0
    repairs: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_paise: int = 0  # placeholder: free tiers; integer paise (hard rule 3)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "RunBudget":
        return cls(max_calls=(settings or get_settings()).llm_max_calls_per_run)

    def charge_call(self) -> None:
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetExceeded(f"run used its {self.max_calls} LLM calls")
            self.calls += 1

    def bump(self, counter: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, counter, getattr(self, counter) + n)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {k: v for k, v in vars(self).items() if not k.startswith("_")}


class ResponseCache:
    """Dev-only disk cache: one JSON file per sha256 key."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    @staticmethod
    def key(provider: str, model: str, messages: Sequence[BaseMessage], schema: str | None) -> str:
        payload = {
            "provider": provider,
            "model": model,
            "messages": [[m.type, m.content] for m in messages],
            "schema": schema,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        path = self.dir / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f"{key}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / f"{key}.json")


@dataclass(frozen=True)
class Target:
    """A chat model plus the provider/model labels used for cache keys and logs."""

    provider: str
    model: str
    chat: BaseChatModel


class LLMClient:
    def __init__(
        self,
        primary: Target,
        fallback: Target | None = None,
        *,
        budget: RunBudget,
        settings: Settings | None = None,
        cache: ResponseCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.s = settings or get_settings()
        self.targets = [primary] + ([fallback] if fallback else [])
        self.budget, self.cache, self._sleep = budget, cache, sleep

    @classmethod
    def for_role(
        cls, role: Role, budget: RunBudget | None = None, settings: Settings | None = None
    ) -> "LLMClient":
        s = settings or get_settings()
        primary_provider = s.llm_provider if role == "main" else s.llm_classifier_provider
        primary = Target(
            primary_provider,
            model_name(role, primary_provider, s),
            get_chat_model(role, primary_provider, s),
        )
        fallback = None
        fb = s.llm_fallback_provider
        if (fb, model_name(role, fb, s)) != (primary.provider, primary.model):
            try:
                fallback = Target(fb, model_name(role, fb, s), get_chat_model(role, fb, s))
            except MissingAPIKey as e:
                log.warning("LLM fallback disabled: %s", e)
        cache = ResponseCache(s.llm_cache_dir) if s.llm_cache else None
        budget = budget or RunBudget.from_settings(s)
        return cls(primary, fallback, budget=budget, settings=s, cache=cache)

    def invoke(
        self, messages: Sequence[MessageLikeRepresentation], *, schema: str | None = None
    ) -> AIMessage:
        msgs = convert_to_messages(messages)
        self.budget.charge_call()
        for i, target in enumerate(self.targets):
            if i:
                self.budget.bump("fallbacks")
                log.warning("LLM rate limited; falling back to %s", target.provider)
            reply = self._invoke_target(target, msgs, schema)
            if reply is not None:
                return reply
        raise RateLimited("all LLM providers are rate limited")

    def _invoke_target(
        self, target: Target, msgs: list[BaseMessage], schema: str | None
    ) -> AIMessage | None:
        """The reply, or None if still rate limited after retries. Other errors propagate."""
        key = ResponseCache.key(target.provider, target.model, msgs, schema) if self.cache else ""
        if self.cache and (hit := self.cache.get(key)) is not None:
            self.budget.bump("cache_hits")
            return AIMessage(content=hit["content"])
        for attempt in range(self.s.llm_retry_attempts + 1):
            try:
                reply = target.chat.invoke(msgs)
            except Exception as e:
                if not is_rate_limit(e):
                    raise
                if attempt == self.s.llm_retry_attempts:
                    return None
                self.budget.bump("retries")
                delay = self.s.llm_retry_base_seconds * 2**attempt
                self._sleep(min(delay, self.s.llm_retry_max_seconds))
                continue
            usage = getattr(reply, "usage_metadata", None) or {}
            self.budget.bump("input_tokens", usage.get("input_tokens", 0))
            self.budget.bump("output_tokens", usage.get("output_tokens", 0))
            if self.cache:
                self.cache.put(key, {"content": reply.content})
            return reply
        return None

    def invoke_structured[T: BaseModel](
        self, messages: Sequence[MessageLikeRepresentation], schema: type[T]
    ) -> T:
        """Ask for JSON matching `schema`; on invalid output send the error back exactly once."""
        msgs = [_json_instruction(schema), *convert_to_messages(messages)]
        raw = _text(self.invoke(msgs, schema=schema.__name__))
        try:
            return _parse(raw, schema)
        except ValidationError as e:
            error = _short_errors(e)
        self.budget.bump("repairs")
        repair = [
            *msgs,
            AIMessage(content=raw),
            HumanMessage(
                content=f"That reply was not valid: {error}\n"
                "Reply again with only the corrected JSON object."
            ),
        ]
        raw = _text(self.invoke(repair, schema=schema.__name__))
        try:
            return _parse(raw, schema)
        except ValidationError as e:
            raise StructuredOutputError(schema.__name__, _short_errors(e), raw) from e


def _json_instruction(schema: type[BaseModel]) -> SystemMessage:
    return SystemMessage(
        content="Reply with only one JSON object (no prose, no code fences) that matches this "
        f"JSON schema:\n{json.dumps(schema.model_json_schema(), sort_keys=True)}"
    )


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse[T: BaseModel](raw: str, schema: type[T]) -> T:
    text = raw.strip()
    if m := _FENCE.match(text):
        text = m.group(1)
    return schema.model_validate_json(text)


def _text(reply: AIMessage) -> str:
    content: Any = reply.content
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)


def _short_errors(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}" for err in e.errors()
    )
