"""Boundary: every handler is actually registered, and updates reach the right one.

Handlers that exist but are not registered fail silently, so this guards the wiring.
"""

from datetime import datetime

import pytest
from telegram import Chat, Message, PhotoSize, Update
from telegram import Document as TgDocument
from telegram.ext import CallbackQueryHandler, TypeHandler

from pfa.bot import handlers
from pfa.bot.app import build_application


@pytest.fixture
def application(settings):
    return build_application(settings, chat_graph=object())


def _flat(application):
    return [h for group in application.handlers.values() for h in group]


def _message(**fields) -> Update:
    message = Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=42, type="private"),
        **fields,
    )
    return Update(update_id=1, message=message)


def _matching_callbacks(application, update):
    """Callbacks of the first handler per group that accepts the update."""
    found = []
    for group in sorted(application.handlers):
        for handler in application.handlers[group]:
            if handler.check_update(update):
                found.append(handler.callback)
                break
    return found


def test_all_handlers_and_error_handler_are_registered(application):
    callbacks = {h.callback for h in _flat(application)}
    assert {
        handlers.handle_text,
        handlers.handle_upload,
        handlers.handle_callback,
        handlers.log_update,
    } <= callbacks
    assert handlers.handle_error in application.error_handlers


def test_every_update_is_logged_before_other_handlers(application):
    logger_handlers = application.handlers[-1]
    assert [type(h) for h in logger_handlers] == [TypeHandler]
    assert logger_handlers[0].callback is handlers.log_update


def test_photo_is_routed_to_upload_handler(application):
    photo = PhotoSize("fid", "uid", width=10, height=10)
    update = _message(photo=(photo,))
    assert handlers.handle_upload in _matching_callbacks(application, update)
    assert handlers.handle_text not in _matching_callbacks(application, update)


def test_image_document_is_routed_to_upload_handler(application):
    document = TgDocument("fid", "uid", file_name="r.png", mime_type="image/png")
    update = _message(document=document)
    assert handlers.handle_upload in _matching_callbacks(application, update)


def test_text_is_routed_to_text_handler_only(application):
    update = _message(text="hello")
    matched = _matching_callbacks(application, update)
    assert handlers.handle_text in matched
    assert handlers.handle_upload not in matched


def test_callback_query_handler_is_registered(application):
    assert any(isinstance(h, CallbackQueryHandler) for h in _flat(application))


def test_login_command_is_registered(application):
    from telegram.ext import CommandHandler

    commands = {
        command
        for h in _flat(application)
        if isinstance(h, CommandHandler) and h.callback is handlers.handle_login
        for command in h.commands
    }
    assert commands == {"login"}


def test_signout_command_is_registered(application):
    from telegram.ext import CommandHandler

    commands = {
        command
        for h in _flat(application)
        if isinstance(h, CommandHandler) and h.callback is handlers.handle_signout
        for command in h.commands
    }
    assert commands == {"signout"}
