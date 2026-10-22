from functools import lru_cache
from typing import Literal

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

    jwt_secret: str = "dev-only-change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
