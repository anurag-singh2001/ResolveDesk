from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "groq", "ollama"]


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

    # HS256 needs >= 32 bytes of key (RFC 7518 3.2); shorter secrets fail at startup.
    jwt_secret: str = Field(default="dev-only-change-me-dev-only-change-me", min_length=32)
    jwt_ttl_minutes: int = 480
    # Demo login: every seeded user signs in with this password. Off outside demos.
    demo_auth: bool = True
    demo_password: str = "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
