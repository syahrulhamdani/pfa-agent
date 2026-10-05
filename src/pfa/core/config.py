"""Application settings, loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """pfa configuration.

    Values come from the process environment. For development and testing, start
    the app with `uv run --env-file .env.example ...`.
    """

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+asyncpg://pfa:pfa@localhost:5432/pfa"
    telegram_bot_token: str = Field(min_length=1)
    telegram_chat_id: int
    gemini_api_key: str = Field(min_length=1)
    gemini_chat_model: str = "gemini-flash-lite-latest"
    gemini_extract_model: str = "gemini-pro-latest"
    web_base_url: str = "http://localhost:5173"
    timezone: str = "Asia/Jakarta"
    log_level: str = "INFO"
    log_use_basic_format: bool = True


@lru_cache
def get_settings() -> Settings:
    """Returns the cached application settings."""
    return Settings()  # type: ignore[call-arg]
