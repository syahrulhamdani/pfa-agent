"""Boundary: Settings reads env vars, applies defaults, rejects missing secrets."""

import pytest
from pydantic import ValidationError

from pfa.core.config import Settings


def test_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "7")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("LOG_USE_BASIC_FORMAT", "false")
    s = Settings()
    assert s.telegram_chat_id == 7
    assert s.log_use_basic_format is False
    assert s.gemini_chat_model  # default present


def test_settings_requires_secrets(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_empty_token():
    with pytest.raises(ValidationError):
        Settings(telegram_bot_token="", telegram_chat_id=1, gemini_api_key="k")


def test_tracing_requires_flag_and_key():
    base = {"telegram_bot_token": "t", "telegram_chat_id": 1, "gemini_api_key": "k"}
    assert not Settings(**base).tracing_enabled
    assert not Settings(**base, langsmith_tracing=True).tracing_enabled
    assert not Settings(**base, langsmith_api_key="ls").tracing_enabled
    on = Settings(**base, langsmith_tracing=True, langsmith_api_key="ls")
    assert on.tracing_enabled


def test_checkpoint_conn_string_drops_asyncpg_driver():
    s = Settings(
        telegram_bot_token="t",
        telegram_chat_id=1,
        gemini_api_key="k",
        database_url="postgresql+asyncpg://u:p@h:5432/d",
    )
    assert s.checkpoint_conn_string == "postgresql://u:p@h:5432/d"
