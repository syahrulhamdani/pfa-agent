"""Boundary: only the configured chat gets answers; LLM failures degrade politely."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pfa.bot.handlers import handle_text, is_authorized
from pfa.core.exceptions import LLMError
from pfa.graphs.chat import BUSY_REPLY


def _update(chat_id: int | None, text: str | None = "hi"):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    chat = None if chat_id is None else SimpleNamespace(id=chat_id)
    return SimpleNamespace(effective_chat=chat, effective_message=message)


def _context():
    return SimpleNamespace(bot_data={"chat_id": 42, "chat_graph": object()})


def test_is_authorized():
    assert is_authorized(_update(42), 42)
    assert not is_authorized(_update(7), 42)
    assert not is_authorized(_update(None), 42)


async def test_unauthorized_chat_gets_no_reply():
    update = _update(7)
    with patch("pfa.bot.handlers.chat_reply", new=AsyncMock()) as chat:
        await handle_text(update, _context())
    chat.assert_not_called()
    update.effective_message.reply_text.assert_not_called()


async def test_authorized_chat_gets_reply():
    update = _update(42)
    with patch("pfa.bot.handlers.chat_reply", new=AsyncMock(return_value="Hello")):
        await handle_text(update, _context())
    update.effective_message.reply_text.assert_awaited_once_with("Hello")


async def test_llm_failure_sends_busy_reply():
    update = _update(42)
    failing = AsyncMock(side_effect=LLMError("x"))
    with patch("pfa.bot.handlers.chat_reply", new=failing):
        await handle_text(update, _context())
    update.effective_message.reply_text.assert_awaited_once_with(BUSY_REPLY)


async def test_message_without_text_is_ignored():
    update = _update(42, text=None)
    with patch("pfa.bot.handlers.chat_reply", new=AsyncMock()) as chat:
        await handle_text(update, _context())
    chat.assert_not_called()
