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

    database_url: str = "postgresql+asyncpg://pfa:pfa@localhost:5433/pfa"
    telegram_bot_token: str = Field(min_length=1)
    telegram_chat_id: int
    gemini_api_key: str = Field(min_length=1)
    gemini_chat_model: str = "gemini-flash-lite-latest"
    gemini_extract_model: str = "gemini-pro-latest"
    upload_dir: str = "data/uploads"
    categories_file: str = "config/categories.json"
    # Web sign-in. AUTH_SECRET signs every token, so keep it long, random and private.
    auth_secret: str = Field(min_length=32)
    auth_link_ttl_minutes: int = Field(10, gt=0)
    auth_session_days: int = Field(7, gt=0)
    auth_cookie_secure: bool = False  # set true when the web app is served over HTTPS
    web_base_url: str = "http://localhost:5173"
    timezone: str = "Asia/Jakarta"
    log_level: str = "INFO"
    log_use_basic_format: bool = True
    # LangSmith observability. LangChain and LangGraph read the LANGSMITH_* env
    # vars directly; these fields exist so the app can report its tracing state.
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "pfa"

    @property
    def checkpoint_conn_string(self) -> str:
        """Returns DATABASE_URL in the plain form psycopg expects."""
        return self.database_url.replace("+asyncpg", "", 1)

    @property
    def tracing_enabled(self) -> bool:
        """True when LangSmith tracing is on and an API key is present."""
        return self.langsmith_tracing and bool(self.langsmith_api_key)


@lru_cache
def get_settings() -> Settings:
    """Returns the cached application settings."""
    return Settings()  # type: ignore[call-arg]
