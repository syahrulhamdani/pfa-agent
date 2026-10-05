"""Gemini model factories: Flash Lite for chat, Pro for extraction."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from pfa.core.config import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Returns the fast model used for chat and recommendations."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.gemini_api_key,
        max_retries=1,
        timeout=30,
    )


def build_extract_model(settings: Settings) -> BaseChatModel:
    """Returns the stronger model used to extract uploads."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_extract_model,
        google_api_key=settings.gemini_api_key,
        max_retries=1,
        timeout=120,
    )
