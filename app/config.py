from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "groq", "ollama"]
DEV_JWT_SECRET = "dev-only-change-me-dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DB URLs are optional so the app and unit tests start without a database.
    database_url: str | None = None
    test_database_url: str | None = None
    migration_database_url: str | None = None
    test_migration_database_url: str | None = None
    # Dev reseed / test cleanup: may delete engine rows, but RLS applies (NOBYPASSRLS).
    maint_database_url: str | None = None
    test_maint_database_url: str | None = None

    llm_provider: Provider = "gemini"
    llm_classifier_provider: Provider = "groq"
    llm_fallback_provider: Provider = "groq"
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    llm_cache: bool = False
    llm_cache_dir: str = ".llm_cache"
    # Model per role and provider (PROJECT.md section 4: model names live in config only).
    llm_main_model_gemini: str = "gemini-2.5-flash"
    llm_classifier_model_gemini: str = "gemini-2.5-flash-lite"
    llm_main_model_groq: str = "llama-3.3-70b-versatile"
    llm_classifier_model_groq: str = "llama-3.1-8b-instant"
    llm_ollama_model: str = "qwen2.5:3b"
    llm_temperature: float = 0.0
    # Rate-limit backoff: retries per provider, delay = base * 2**attempt, capped.
    llm_retry_attempts: int = Field(default=3, ge=0)
    llm_retry_base_seconds: float = Field(default=1.0, ge=0)
    llm_retry_max_seconds: float = Field(default=20.0, ge=0)
    # Engine limit (PROJECT.md section 8): more LLM calls in one run -> stop and escalate.
    llm_max_calls_per_run: int = Field(default=8, ge=1)
    # How a new case is worked: deterministic (customer picks a category, code proposes)
    # or agents (free text -> LangGraph: classify, investigate, policy, resolve).
    engine_mode: Literal["deterministic", "agents"] = "deterministic"

    # Fail safe: an unset APP_ENV is treated as prod (dev/test must opt in explicitly).
    app_env: Literal["dev", "test", "prod"] = "prod"

    # HS256 needs >= 32 bytes of key (RFC 7518 3.2); shorter secrets fail at startup.
    jwt_secret: str = Field(default=DEV_JWT_SECRET, min_length=32)
    jwt_ttl_minutes: int = 60
    jwt_issuer: str = "resolvedesk"
    jwt_audience: str = "resolvedesk-api"
    # Demo login: every seeded user signs in with one password. Opt-in, never in prod.
    demo_auth: bool = False
    demo_password: str = "demo"

    @model_validator(mode="after")
    def _no_dev_shortcuts_in_prod(self) -> "Settings":
        if self.app_env == "prod" and (self.demo_auth or self.jwt_secret == DEV_JWT_SECRET):
            raise ValueError("prod requires DEMO_AUTH=false and a real JWT_SECRET")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
