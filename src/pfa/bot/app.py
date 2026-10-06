"""Builds the Telegram application."""

from langgraph.graph.state import CompiledStateGraph
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from pfa.bot.handlers import (
    handle_callback,
    handle_demo_nudge,
    handle_error,
    handle_login,
    handle_signout,
    handle_text,
    handle_upload,
    log_update,
)
from pfa.core.config import Settings


def build_application(
    settings: Settings, chat_graph: CompiledStateGraph
) -> Application:
    """Creates the Telegram application with its handlers registered.

    The app is started by the FastAPI lifespan, not by `run_polling`, so it can
    share one event loop with the API. The lifespan adds the upload coordinator
    to `bot_data["coordinator"]` before polling starts.
    """
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["chat_id"] = settings.telegram_chat_id
    application.bot_data["chat_graph"] = chat_graph

    application.add_error_handler(handle_error)
    # Group -1 runs before the real handlers and never consumes the update.
    application.add_handler(TypeHandler(Update, log_update), group=-1)
    application.add_handler(CommandHandler("login", handle_login))
    application.add_handler(CommandHandler("signout", handle_signout))
    application.add_handler(CommandHandler("demo_nudge", handle_demo_nudge))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.ALL, handle_upload)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    return application
