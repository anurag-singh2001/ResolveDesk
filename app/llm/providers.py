"""LLM provider factory, rate-limit fallback, structured output and dev cache (PROJECT.md 4, 8).

Providers and model names come from settings only. `LLMClient` is the one way agents call a
model: it counts every call and every provider request against the run's `RunBudget`, backs
off on rate limits and then switches to the fallback provider, and validates structured
replies with one repair attempt.
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


class ProviderFailed(LLMError):
    """Every provider failed with a non-rate-limit error (server error, retired model...).
    Only the exception class names are kept: SDK messages can echo request details."""


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
            google_api_key=s.gemini_api_key.get_secret_value(),
            temperature=s.llm_temperature,
            max_retries=0,
        )
    if provider == "groq":
        if not s.groq_api_key:
            raise MissingAPIKey(provider)
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=name,
            api_key=s.groq_api_key.get_secret_value(),
            temperature=s.llm_temperature,
            max_retries=0,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=name, base_url=s.ollama_base_url, temperature=s.llm_temperature)
    raise ValueError(f"unknown LLM provider {provider!r}")


_RATE_LIMIT_TEXT = ("rate limit", "ratelimit", "resource_exhausted", "too many requests")


def is_rate_limit(exc: BaseException) -> bool:
    """Generic 429 detection: provider SDKs use different exception types for the same thing.

    An HTTP status attribute decides when there is one (`status_code`, `response.status_code`,
    `code`). Only without one is the text matched, by phrase: a bare "429" in a message may be
    a port or a request id, so it is not treated as a rate limit.
    """
    response = getattr(exc, "response", None)
    statuses = [
        s
        for s in (
            getattr(exc, "status_code", None),
            getattr(response, "status_code", None),
            getattr(exc, "code", None),
        )
        if isinstance(s, int) and not isinstance(s, bool)
    ]
    if statuses:
        return 429 in statuses
    text = f"{type(exc).__name__} {exc}".lower()
    return any(t in text for t in _RATE_LIMIT_TEXT)


@dataclass
class RunBudget:
    """Per-run LLM counters and the two run limits; either one raises `BudgetExceeded`.

    - `calls` / `max_calls` (`llm_max_calls_per_run`): logical calls. One per `invoke`, so a
      structured-output repair counts as a call and so does a cache hit (a run routes the same
      with or without the dev cache). Rate-limit retries and fallbacks do not count here.
    - `provider_requests` / `max_provider_requests` (`llm_max_provider_requests_per_run`):
      every request actually sent to a provider, retries and fallbacks included; cache hits
      send none. Bounds the cost of retry x fallback storms that `max_calls` does not see.

    Tokens count real provider replies only.
    """

    max_calls: int
    max_provider_requests: int = 24
    calls: int = 0
    provider_requests: int = 0
    retries: int = 0
    fallbacks: int = 0
    repairs: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_paise: int = 0  # placeholder: free tiers; integer paise (hard rule 3)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    # Per (role, provider, model) usage for the persisted records (S9.2). Numbers and class
    # names only. Underscore: not part of snapshot().
    _usage: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict, repr=False, compare=False
    )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "RunBudget":
        s = settings or get_settings()
        return cls(
            max_calls=s.llm_max_calls_per_run,
            max_provider_requests=s.llm_max_provider_requests_per_run,
        )

    def charge_call(self) -> None:
        """One logical call (an `invoke`, incl. repairs and cache hits)."""
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetExceeded(f"run used its {self.max_calls} LLM calls")
            self.calls += 1

    def charge_provider_request(self) -> None:
        """One request about to be sent to a provider (first try, retry or fallback)."""
        with self._lock:
            if self.provider_requests >= self.max_provider_requests:
                raise BudgetExceeded(
                    f"run used its {self.max_provider_requests} LLM provider requests"
                )
            self.provider_requests += 1

    def bump(self, counter: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, counter, getattr(self, counter) + n)

    def note_request(
        self,
        role: str,
        provider: str,
        model: str,
        *,
        latency_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error_class: str | None = None,
        fallback: bool = False,
    ) -> None:
        """One request that reached a provider (cache hits send none)."""
        with self._lock:
            u = self._usage.setdefault(
                (role, provider, model),
                {"calls": 0, "input_tokens": 0, "output_tokens": 0, "failures": 0,
                 "latency_ms": 0, "fallback": False, "error_class": None},
            )  # fmt: skip
            u["calls"] += 1
            u["input_tokens"] += input_tokens
            u["output_tokens"] += output_tokens
            u["latency_ms"] += latency_ms
            u["fallback"] = u["fallback"] or fallback
            if error_class:
                u["failures"] += 1
                u["error_class"] = error_class

    def take_usage(self) -> list[dict[str, Any]]:
        """The per-model usage so far, cleared so a second recording cannot double count."""
        with self._lock:
            rows = [
                {"role": r, "provider": p, "model": m, **u} for (r, p, m), u in self._usage.items()
            ]
            self._usage.clear()
        return rows

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
        role: str = "main",
    ):
        self.s = settings or get_settings()
        self.targets = [primary] + ([fallback] if fallback else [])
        self.budget, self.cache, self._sleep = budget, cache, sleep
        self.role = role

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
        return cls(primary, fallback, budget=budget, settings=s, cache=cache, role=role)

    def invoke(
        self, messages: Sequence[MessageLikeRepresentation], *, schema: str | None = None
    ) -> AIMessage:
        msgs = convert_to_messages(messages)
        self.budget.charge_call()
        failures: list[str] = []
        for i, target in enumerate(self.targets):
            if i:
                self.budget.bump("fallbacks")
                log.warning("LLM %s failed; falling back to %s", self.targets[i - 1].provider,
                            target.provider)  # fmt: skip
            try:
                reply = self._invoke_target(target, msgs, schema)
            except LLMError:
                raise  # our own (e.g. the budget): never retried on another provider
            except Exception as e:  # server error, retired model, network: try the next one
                failures.append(f"{target.provider}:{type(e).__name__}")
                continue
            if reply is not None:
                return reply
            failures.append(f"{target.provider}:rate_limited")
        if all(f.endswith(":rate_limited") for f in failures):
            raise RateLimited("all LLM providers are rate limited")
        raise ProviderFailed(", ".join(failures))

    def _invoke_target(
        self, target: Target, msgs: list[BaseMessage], schema: str | None
    ) -> AIMessage | None:
        """The reply, or None if still rate limited after retries. Other errors propagate."""
        key = ResponseCache.key(target.provider, target.model, msgs, schema) if self.cache else ""
        if self.cache and (hit := self.cache.get(key)) is not None:
            self.budget.bump("cache_hits")
            return AIMessage(content=hit["content"])
        for attempt in range(self.s.llm_retry_attempts + 1):
            self.budget.charge_provider_request()
            started = time.monotonic()
            try:
                reply = target.chat.invoke(msgs)
            except Exception as e:
                self._note(target, started, error_class=type(e).__name__)
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
            self._note(target, started, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            if self.cache:
                self.cache.put(key, {"content": reply.content})
            return reply
        return None

    def _note(
        self, target: Target, started: float, tin: int = 0, tout: int = 0,
        error_class: str | None = None,
    ) -> None:  # fmt: skip
        self.budget.note_request(
            self.role,
            target.provider,
            target.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=tin,
            output_tokens=tout,
            error_class=error_class,
            fallback=target is not self.targets[0],
        )

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
