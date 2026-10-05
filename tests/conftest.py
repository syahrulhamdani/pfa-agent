"""Shared fixtures."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from pfa.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings with dummy secrets, never read from the real environment."""
    return Settings(
        telegram_bot_token="123:abc",
        telegram_chat_id=42,
        gemini_api_key="fake-key",
    )


@pytest.fixture
def fake_model_factory():
    """Builds a fake chat model that replays the given reply texts in order."""

    def _build(*replies: str) -> GenericFakeChatModel:
        return GenericFakeChatModel(
            messages=iter(AIMessage(content=r) for r in replies)
        )

    return _build
