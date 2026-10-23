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

    llm_provider: Provider = "gemini"
    llm_classifier_provider: Provider = "groq"
    llm_fallback_provider: Provider = "groq"
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    llm_cache: bool = False

    app_env: Literal["dev", "test", "prod"] = "dev"

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
