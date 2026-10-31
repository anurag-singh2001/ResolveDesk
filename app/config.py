import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "groq", "ollama"]
PricePaise = Annotated[int, Field(ge=0, le=10**9)]
DEV_JWT_SECRET = "dev-only-change-me-dev-only-change-me"


class Settings(BaseSettings):
    # hide_input_in_errors: a ValidationError never echoes the values (API keys, DB URLs).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

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
    # SecretStr: str()/repr() print "**********"; unwrap only where the key is handed to the SDK.
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"
    # Dev only: the cache stores full prompts and replies, customer text included (refused in prod).
    llm_cache: bool = False
    llm_cache_dir: str = ".llm_cache"
    # Model per role and provider (PROJECT.md section 4: model names live in config only).
    llm_main_model_gemini: str = "gemini-3.8-flash"
    llm_classifier_model_gemini: str = "gemini-3.5-flash-lite"
    llm_main_model_groq: str = "openai/gpt-oss-120b"
    llm_classifier_model_groq: str = "openai/gpt-oss-20b"
    llm_ollama_model: str = "qwen2.5:3b"
    llm_temperature: float = 0.0
    # Rate-limit backoff: retries per provider, delay = base * 2**attempt, capped.
    llm_retry_attempts: int = Field(default=3, ge=0)
    llm_retry_base_seconds: float = Field(default=1.0, ge=0)
    llm_retry_max_seconds: float = Field(default=20.0, ge=0)
    # Engine limits (PROJECT.md section 8); past either one the run stops and escalates.
    # Logical calls: each invoke and each structured-output repair, cache hits included;
    # rate-limit retries and fallbacks are not counted here.
    llm_max_calls_per_run: int = Field(default=8, ge=1)
    # How a new case is worked: deterministic (customer picks a category, code proposes)
    # or agents (free text -> LangGraph: classify, investigate, policy, resolve).
    engine_mode: Literal["deterministic", "agents"] = "deterministic"
    # Classifier guesses below this confidence ask the customer instead of proceeding.
    agent_min_confidence: float = Field(default=0.6, ge=0, le=1)
    # Actual provider requests: every request sent, retries and fallbacks included
    # (cache hits send none). Bounds the worst case of retry * fallback per logical call.
    llm_max_provider_requests_per_run: int = Field(default=24, ge=1)
    # ESTIMATE price table for the usage records (S9.2): "provider/model" -> [input, output]
    # paise per million tokens, integers (hard rule 3). Unlisted models cost 0 (free tiers).
    # Not a bill: check the provider's invoice. Env: LLM_PRICES_PAISE_PER_MILLION='{"a/b":[1,2]}'.
    # Each price is capped (1e9 paise = 10 million rupees per million tokens) so a typo cannot
    # overflow the bigint cost column.
    llm_prices_paise_per_million: dict[str, tuple[PricePaise, PricePaise]] = {}

    # Dev only: JSON file the mock providers keep their records in, so they survive an API
    # restart. Unset = in memory (tests, default).
    mock_state_file: str | None = None

    # Fail safe: an unset APP_ENV is treated as prod (dev/test must opt in explicitly).
    app_env: Literal["dev", "test", "prod"] = "prod"

    # HS256 needs >= 32 bytes of key (RFC 7518 3.2); shorter secrets fail at startup.
    jwt_secret: str = Field(default=DEV_JWT_SECRET, min_length=32)
    jwt_ttl_minutes: int = 60
    jwt_issuer: str = "resolvedesk"
    jwt_audience: str = "resolvedesk-api"
    # Demo accounts: seeded users get the demo password from their tenant folder, and
    # GET /auth/demo-accounts lists them. Opt-in, never in prod. Login itself is always bcrypt.
    demo_auth: bool = False
    # bcrypt work factor (2**rounds). Tests lower it; stored hashes keep their own cost.
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    # Lockout: this many failed logins for one tenant+email within the window -> 429.
    login_max_failures: int = Field(default=5, ge=1)
    login_window_minutes: int = Field(default=15, ge=1)
    # In-app job scheduler (S9.3). OFF by default (dev, test and prod alike): a deployment opts in.
    # Per job, an interval in seconds; 0 switches that job off.
    scheduler_enabled: bool = False
    scheduler_tick_seconds: float = Field(default=30.0, gt=0)
    scheduler_startup_delay_seconds: float = Field(default=60.0, ge=0)  # first run after boot
    scheduler_shutdown_grace_seconds: float = Field(default=10.0, ge=0)
    scheduler_sweep_interval_seconds: int = Field(default=300, ge=0)
    scheduler_retention_interval_seconds: int = Field(default=86_400, ge=0)
    scheduler_growth_interval_seconds: int = Field(default=86_400, ge=0)
    # Retention stays a dry run unless this is set: redaction cannot be undone.
    scheduler_retention_apply: bool = False
    scheduler_alerts_interval_seconds: int = Field(default=300, ge=0)
    # Error log and alerts (S9.4). The handler is installed with the app (lifespan); rate limit =
    # at most one database write per distinct error per this many seconds (the rest is counted).
    error_log_enabled: bool = True
    error_log_flush_seconds: float = Field(default=10.0, ge=0)
    # Alert rule thresholds. Whole numbers only: rates are in basis points (100 = 1%).
    alert_window_hours: int = Field(default=1, ge=1)  # provider failure window
    alert_provider_failure_bps: int = Field(default=2000, ge=1)
    alert_provider_min_calls: int = Field(default=10, ge=1)  # too few calls: no verdict
    alert_job_lookback_hours: int = Field(default=24, ge=1)  # a failed job older than this clears
    alert_escalation_min_count: int = Field(default=5, ge=1)  # last 24h escalations at least
    alert_escalation_ratio_pct: int = Field(default=300, ge=101)  # vs the prior 7-day daily mean
    alert_eval_drop_points: int = Field(default=5, ge=1)  # pass-rate drop, percentage points
    alert_stuck_minutes: int = Field(default=30, ge=1)  # a job 'running' longer than this
    alert_eval_reports_dir: str = "evals/reports"
    # Platform admin (S9.1): one operator principal, configured only here (never in the DB).
    # The feature is ON only when email, bcrypt hash AND the platform DB URL are all set; any
    # missing piece and every /platform route answers 404 (fail closed).
    platform_admin_email: str | None = None
    platform_admin_password_hash: SecretStr | None = None
    # Connection for the aggregate-only role resolvedesk_platform (no table rights, no tenant).
    platform_database_url: str | None = None
    # Signing key for platform tokens: SEPARATE from JWT_SECRET, required (no default), so a
    # tenant secret, or the public dev secret, can never forge a platform token in any env.
    platform_jwt_secret: SecretStr | None = None
    platform_jwt_ttl_minutes: int = Field(default=30, ge=1, le=240)
    platform_jwt_audience: str = "resolvedesk-platform"
    # Browser origins allowed by CORS, comma-separated (the React app's dev server by default).
    web_origins: str = "http://localhost:5173"

    @property
    def web_origin_list(self) -> list[str]:
        return [o.strip() for o in self.web_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _no_dev_shortcuts_in_prod(self) -> "Settings":
        if self.app_env == "prod" and (self.demo_auth or self.jwt_secret == DEV_JWT_SECRET):
            raise ValueError("prod requires DEMO_AUTH=false and a real JWT_SECRET")
        if self.app_env == "prod" and self.llm_cache:
            raise ValueError("prod requires LLM_CACHE=false (the cache stores customer text)")
        return self


def platform_admin_enabled(s: Settings) -> bool:
    """All four pieces present and non-blank; the platform secret strong and distinct.
    Anything less keeps the platform routes off."""
    secret = s.platform_jwt_secret.get_secret_value() if s.platform_jwt_secret else ""
    if len(secret) < 32 or secret in (DEV_JWT_SECRET, s.jwt_secret):
        return False
    return bool(
        (s.platform_admin_email or "").strip()
        and s.platform_admin_password_hash is not None
        and s.platform_admin_password_hash.get_secret_value().strip()
        and (s.platform_database_url or "").strip()
    )


@lru_cache
def get_settings() -> Settings:
    # ENV_FILE points at another dotenv file (e.g. a second checkout reusing the main one's
    # keys). Real environment variables still win over anything in the file.
    return Settings(_env_file=os.environ.get("ENV_FILE", ".env"))
