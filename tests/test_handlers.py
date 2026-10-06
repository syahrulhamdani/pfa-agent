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


def _callback_update(data: str, chat_id: int = 42):
    query = SimpleNamespace(
        data=data, answer=AsyncMock(), edit_message_reply_markup=AsyncMock()
    )
    return SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=None,
    )


def _upload_context(coordinator):
    return SimpleNamespace(
        bot_data={"chat_id": 42, "chat_graph": object(), "coordinator": coordinator},
        bot=SimpleNamespace(send_message=AsyncMock()),
    )


async def test_confirm_button_resumes_with_confirm():
    from pfa.bot.handlers import handle_callback

    coordinator = SimpleNamespace(resume=AsyncMock())
    await handle_callback(_callback_update("confirm:7"), _upload_context(coordinator))
    coordinator.resume.assert_awaited_once_with(7, {"action": "confirm"})


async def test_card_button_resumes_with_card_id():
    from pfa.bot.handlers import handle_callback

    coordinator = SimpleNamespace(resume=AsyncMock())
    await handle_callback(_callback_update("card:7:3"), _upload_context(coordinator))
    coordinator.resume.assert_awaited_once_with(7, {"action": "set_card", "card_id": 3})


async def test_malformed_or_foreign_callbacks_are_ignored():
    from pfa.bot.handlers import handle_callback

    coordinator = SimpleNamespace(resume=AsyncMock())
    for update in (
        _callback_update("confirm:abc"),
        _callback_update("card:1:x"),
        _callback_update("bogus"),
        _callback_update("confirm:7", chat_id=99),
    ):
        await handle_callback(update, _upload_context(coordinator))
    coordinator.resume.assert_not_called()


async def test_non_image_document_gets_unsupported_reply():
    from pfa.bot.formatting import UNSUPPORTED_TEXT
    from pfa.bot.handlers import handle_upload

    message = SimpleNamespace(
        photo=[],
        document=SimpleNamespace(mime_type="application/pdf", file_id="f"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=42), effective_message=message
    )
    coordinator = SimpleNamespace(receive=AsyncMock())
    await handle_upload(update, _upload_context(coordinator))
    message.reply_text.assert_awaited_once_with(UNSUPPORTED_TEXT)
    coordinator.receive.assert_not_called()


async def test_text_goes_to_open_receipt_first():
    update = _update(42, "it was 50000")
    coordinator = SimpleNamespace(resume_text=AsyncMock(return_value=True))
    context = _upload_context(coordinator)
    with patch("pfa.bot.handlers.chat_reply", new=AsyncMock()) as chat:
        await handle_text(update, context)
    chat.assert_not_called()
    update.effective_message.reply_text.assert_not_called()


async def test_error_handler_tells_authorized_user():
    from telegram import Update

    from pfa.bot.formatting import FAILED_TEXT
    from pfa.bot.handlers import handle_error

    update = Update(update_id=1)
    message = SimpleNamespace(reply_text=AsyncMock())
    update._effective_message = message
    update._effective_chat = SimpleNamespace(id=42)
    context = SimpleNamespace(error=RuntimeError("boom"), bot_data={"chat_id": 42})
    await handle_error(update, context)
    message.reply_text.assert_awaited_once_with(FAILED_TEXT)


async def test_error_handler_survives_non_update_objects():
    from pfa.bot.handlers import handle_error

    context = SimpleNamespace(error=RuntimeError("boom"), bot_data={"chat_id": 42})
    await handle_error(None, context)  # must not raise


async def test_login_command_sends_a_link_without_preview():
    from pfa.bot.handlers import handle_login

    update = _update(42, "/login")
    issue = AsyncMock(return_value="http://web/auth?token=T")
    context = SimpleNamespace(
        bot_data={"chat_id": 42, "issue_link": issue, "link_ttl_minutes": 10}
    )
    await handle_login(update, context)
    reply = update.effective_message.reply_text
    reply.assert_awaited_once()
    assert "http://web/auth?token=T" in reply.await_args.args[0]
    assert "10 minutes" in reply.await_args.args[0]
    assert reply.await_args.kwargs["link_preview_options"].is_disabled


async def test_login_command_ignores_other_chats():
    from pfa.bot.handlers import handle_login

    update = _update(7, "/login")
    issue = AsyncMock()
    context = SimpleNamespace(
        bot_data={"chat_id": 42, "issue_link": issue, "link_ttl_minutes": 10}
    )
    await handle_login(update, context)
    issue.assert_not_called()
    update.effective_message.reply_text.assert_not_called()


async def test_signout_command_revokes_and_confirms():
    from pfa.bot.formatting import SIGNED_OUT_TEXT
    from pfa.bot.handlers import handle_signout

    update = _update(42, "/signout")
    revoke = AsyncMock()
    context = SimpleNamespace(bot_data={"chat_id": 42, "revoke_sessions": revoke})
    await handle_signout(update, context)
    revoke.assert_awaited_once()
    update.effective_message.reply_text.assert_awaited_once_with(SIGNED_OUT_TEXT)


async def test_signout_command_ignores_other_chats():
    from pfa.bot.handlers import handle_signout

    update = _update(7, "/signout")
    revoke = AsyncMock()
    context = SimpleNamespace(bot_data={"chat_id": 42, "revoke_sessions": revoke})
    await handle_signout(update, context)
    revoke.assert_not_called()
    update.effective_message.reply_text.assert_not_called()
