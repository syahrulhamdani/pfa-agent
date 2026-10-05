"""Builds the Telegram application."""

from langgraph.graph.state import CompiledStateGraph
from telegram.ext import Application, MessageHandler, filters

from pfa.bot.handlers import handle_text
from pfa.core.config import Settings


def build_application(
    settings: Settings, chat_graph: CompiledStateGraph
) -> Application:
    """Creates the Telegram application with its handlers registered.

    The app is started by the FastAPI lifespan, not by `run_polling`, so it can
    share one event loop with the API.
    """
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["chat_id"] = settings.telegram_chat_id
    application.bot_data["chat_graph"] = chat_graph
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    return application
