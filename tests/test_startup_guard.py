"""Boundary: starting pfa with placeholder settings stops at once, in plain words.

Without this, a newcomer who skips `pfa doctor` gets a stack trace from Telegram
rejecting the placeholder token. What is tested: the message names each unset value and
what to do, a real setup produces no message, and the app really refuses to start.
"""

import pytest

from pfa.core.config import Settings, get_settings
from pfa.core.exceptions import PfaError
from pfa.main import app
from pfa.services.diagnostics import incomplete_setup_message

REAL = {
    "telegram_bot_token": "123456:real-looking-token",
    "telegram_chat_id": 4242,
    "gemini_api_key": "real-looking-key",
    "auth_secret": "real-secret-" + "x" * 40,
}


def settings(**overrides) -> Settings:
    return Settings(**{**REAL, **overrides})


def test_a_real_setup_produces_no_message():
    assert incomplete_setup_message(settings()) is None


@pytest.mark.parametrize(
    ("overrides", "mentions"),
    [
        ({"telegram_bot_token": "replace-me"}, ["Telegram token", "BotFather"]),
        ({"telegram_chat_id": 0}, ["Telegram chat id", "pfa chat-id"]),
        ({"gemini_api_key": "replace-me"}, ["Gemini API key", "aistudio.google.com"]),
        (
            {"auth_secret": "replace-me-" + "x" * 40},
            ["Sign-in secret", "token_urlsafe"],
        ),
        ({"timezone": "Mars/Olympus"}, ["Timezone", "Asia/Jakarta"]),
    ],
)
def test_each_unset_value_is_named_with_what_to_do(overrides, mentions):
    message = incomplete_setup_message(settings(**overrides))
    assert message is not None and message.startswith("pfa is not set up yet:")
    for text in mentions:
        assert text in message
    assert "pfa doctor" in message


def test_every_problem_is_listed_not_just_the_first():
    message = incomplete_setup_message(
        settings(telegram_bot_token="replace-me", telegram_chat_id=0)
    )
    assert "Telegram token" in message and "Telegram chat id" in message
    assert message.count("\n  - ") == 2


def test_the_message_never_contains_a_secret():
    message = incomplete_setup_message(settings(telegram_chat_id=0))
    for secret in ("real-looking-token", "real-looking-key", REAL["auth_secret"]):
        assert secret not in message


async def test_the_app_refuses_to_start_with_placeholders(monkeypatch):
    for name, value in {
        "TELEGRAM_BOT_TOKEN": "replace-me",
        "TELEGRAM_CHAT_ID": "0",
        "GEMINI_API_KEY": "replace-me",
        "AUTH_SECRET": "replace-me-with-at-least-32-random-characters",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        with pytest.raises(PfaError, match="pfa is not set up yet"):
            async with app.router.lifespan_context(app):
                pass  # pragma: no cover - the guard stops it before this
    finally:
        get_settings.cache_clear()
